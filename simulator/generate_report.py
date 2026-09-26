"""
Smart Toothbrush - Report Generator (18-Pos mode)
"""

import os
import re

COLUMN_INDEX = 15
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output')
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'report')

TEMPLATE = [
    (3, 9), (6, 12, 2, 8), (3, 9), (4, 10), (3, 9), (5, 11, 1, 7),
    (6, 12, 2, 8), (5, 11, 1, 7), (4, 10), (5, 11, 1, 7), (1, 5),
    (2, 6), (8, 12), (7, 11), (13,), (14,), (15,), (16,)
]

FACE_PAIR = {1: 2, 2: 1, 3: 6, 6: 3, 4: 5, 5: 4,
             7: 8, 8: 7, 9: 12, 12: 9, 10: 11, 11: 10}

MAX_LINE_LEN = 70  # 最大行宽，与分隔符等宽

def wrap_line(prefix, items, sep=','):
    """将items按sep连接，超过MAX_LINE_LEN则分行，后续行用prefix填充"""
    lines = []
    current = prefix
    for item in items:
        candidate = current + (sep if current != prefix else '') + item
        if len(candidate) > MAX_LINE_LEN and current != prefix:
            lines.append(current)
            current = prefix + item
        else:
            current = candidate
    if current != prefix:
        lines.append(current)
    if not lines:
        lines.append(prefix)
    return '\n'.join(lines)


def count_any_col(filepath, target_col=22, trigger_col=3, trigger_val=1):
    """Count groups of consecutive 1s in target_col after trigger."""
    count = 0
    in_group = False
    triggered = trigger_col is None
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if not triggered:
                if trigger_col >= 1 and trigger_col <= len(parts):
                    try:
                        if int(parts[trigger_col - 1]) == trigger_val:
                            triggered = True
                    except ValueError:
                        continue
                continue
            if target_col >= 1 and target_col <= len(parts):
                try:
                    val = int(parts[target_col - 1])
                    if val == 1:
                        if not in_group:
                            count += 1
                            in_group = True
                    else:
                        in_group = False
                except ValueError:
                    in_group = False
    return count


def read_column_values(filepath, col_index, trigger_col=None, trigger_val=None):
    values = []
    line_numbers = []
    triggered = trigger_col is None
    line_num = 0
    with open(filepath, 'r') as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if not triggered:
                if trigger_col >= 1 and trigger_col <= len(parts):
                    try:
                        if int(parts[trigger_col - 1]) == trigger_val:
                            triggered = True
                    except ValueError:
                        continue
                continue
            if col_index >= 1 and col_index <= len(parts):
                try:
                    values.append(int(parts[col_index - 1]))
                    line_numbers.append(line_num)
                except ValueError:
                    continue
    return values, line_numbers


def deduplicate_with_count(values, line_numbers):
    if not values:
        return [], []
    result_values = []
    result_counts = []
    result_line_numbers = []
    i = 0
    while i < len(values):
        count = 1
        while i + count < len(values) and values[i + count] == values[i]:
            count += 1
        result_values.append(values[i])
        result_counts.append(count)
        result_line_numbers.append(line_numbers[i])
        i += count
    return result_values, result_counts, result_line_numbers


def calc_total_18(matched, deduped_with_count, deduped_line_numbers, exclude_x=False):
    """18个Pos行上显示的所有数的count总和 = primary + 并入Pos行的补分值(pos_extra)。
    直接扫描deduped序列，每个deduped值只计一次：
    line在pos_map → primary；line不在pos_map → pending → 属于tpl_prev → extra。"""
    deduped_values = [v for v, c in deduped_with_count]
    deduped_counts = [c for v, c in deduped_with_count]
    x_pos = set()
    pos_map = {}
    for i, (_, _, is_match, ln) in enumerate(matched, 1):
        if ln is not None:
            pos_map[ln] = i
            if not is_match:
                x_pos.add(i)
    first_pos_ln = min(pos_map.keys()) if pos_map else None
    total = 0
    prev_pos_num = None
    pending = []
    def flush(next_pos_num):
        nonlocal total, prev_pos_num
        if not pending or prev_pos_num is None:
            pending.clear()
            return
        tpl_prev = TEMPLATE[prev_pos_num - 1]
        for val, cnt in pending:
            if val in tpl_prev:
                if not (exclude_x and prev_pos_num in x_pos):
                    total += cnt
        pending.clear()
    for i, val in enumerate(deduped_values):
        ln = deduped_line_numbers[i]
        cnt = deduped_counts[i]
        if first_pos_ln is not None and ln < first_pos_ln:
            continue
        if ln in pos_map:
            flush(pos_map[ln])
            if not (exclude_x and pos_map[ln] in x_pos):
                total += cnt
            prev_pos_num = pos_map[ln]
        else:
            pending.append((val, cnt))
    flush(None)
    return total


def count_signed_standalone(deduped_with_count, matched, deduped_line_numbers):
    """统计明细区最终被标为 '+' 或 '-' 前缀的单列项 count 总和。"""
    deduped_values = [v for v, c in deduped_with_count]
    deduped_counts = [c for v, c in deduped_with_count]
    total = 0
    pos_map = {}
    for i, (_, _, _, ln) in enumerate(matched, 1):
        if ln is not None:
            pos_map[ln] = i
    first_pos_ln = min(pos_map.keys()) if pos_map else None
    prev_pos_num = None
    pending = []

    def flush(next_pos_num):
        nonlocal total
        if not pending:
            return
        tpl_prev = TEMPLATE[prev_pos_num - 1] if prev_pos_num is not None else None
        tpl_next = TEMPLATE[next_pos_num - 1] if next_pos_num is not None else None
        for val, cnt in pending:
            if tpl_prev is not None and val in tpl_prev:
                continue
            if tpl_next is not None and val in tpl_next:
                total += cnt
                continue
            partner = FACE_PAIR.get(val)
            if partner is not None and tpl_prev is not None and partner in tpl_prev:
                total += cnt
            elif partner is not None and tpl_next is not None and partner in tpl_next:
                total += cnt
        pending.clear()

    for i, val in enumerate(deduped_values):
        cnt = deduped_counts[i]
        ln = deduped_line_numbers[i]
        if first_pos_ln is not None and ln < first_pos_ln:
            continue
        if ln in pos_map:
            flush(pos_map[ln])
            prev_pos_num = pos_map[ln]
        else:
            pending.append((val, cnt))
    flush(None)
    return total


def match_template(deduped_with_count, deduped_line_numbers):
    """序列对齐DP：为每18个位置各选一个值，索引严格递增，最大化匹配数
    返回: (result, match_count, selected_orig_indices, leading_ones_count)
    result[i] = (val, count, is_match, line_number)
    selected_orig_indices = 被选中的原始1-based序号集合
    """
    values = [v for v, c in deduped_with_count]
    counts = [c for v, c in deduped_with_count]
    
    # 记录前导1的个数
    start = 0
    while start < len(values) and values[start] == 1:
        start += 1
    vals = values[start:]
    cnts = counts[start:]
    lns = deduped_line_numbers[start:] if deduped_line_numbers else [0] * len(vals)
    nv = len(vals)
    nt = len(TEMPLATE)
    
    # 被选中的原始序号集合（前导1始终算选中）
    selected_orig = set(range(1, start + 1))
    
    if nv < nt:
        return _match_template_fallback(vals, cnts, lns, nv, nt, selected_orig, start)
    
    NEG_INF = -10000
    dp = [[NEG_INF] * (nv + 1) for _ in range(nt + 1)]
    for j in range(nv + 1):
        dp[0][j] = 0
    
    for i in range(1, nt + 1):
        ts = TEMPLATE[i-1]
        for j in range(i, nv + 1):
            dp[i][j] = dp[i][j-1]
            add = 1 if vals[j-1] in ts else 0
            if dp[i-1][j-1] + add > dp[i][j]:
                dp[i][j] = dp[i-1][j-1] + add
    
    match_count = dp[nt][nv]
    
    result = [None] * nt
    i, j = nt, nv
    while i > 0 and j > 0:
        if dp[i][j] == dp[i][j-1]:
            j -= 1
        else:
            is_match = vals[j-1] in TEMPLATE[i-1]
            result[i-1] = (vals[j-1], cnts[j-1], is_match, lns[j-1])
            selected_orig.add(start + j)
            i -= 1
            j -= 1
    
    for k in range(nt):
        if result[k] is None:
            result[k] = (None, 0, False, None)

    for k in range(1, nt):
        val_k, cnt_k, is_match_k, ln_k = result[k]
        if val_k is None:
            continue
        prev_val, prev_cnt, prev_match, prev_ln = result[k - 1]
        if prev_val is None:
            continue
        if not prev_match and prev_val in TEMPLATE[k - 1]:
            result[k - 1] = (prev_val, prev_cnt, True, prev_ln)
    
    return result, match_count, selected_orig, start


def _match_template_fallback(vals, cnts, lns, nv, nt, selected_orig, start):
    """降级逻辑：当非1值不足18个时使用"""
    dp = [[0] * (nv + 1) for _ in range(nt + 1)]
    
    for i in range(1, nt + 1):
        ts = TEMPLATE[i-1]
        for j in range(1, nv + 1):
            dp[i][j] = dp[i][j-1]
            if vals[j-1] in ts:
                if dp[i-1][j-1] + 1 > dp[i][j]:
                    dp[i][j] = dp[i-1][j-1] + 1
            if dp[i-1][j] > dp[i][j]:
                dp[i][j] = dp[i-1][j]
    
    matched_pos = {}
    used_vals = set()
    i, j = nt, nv
    while i > 0 and j > 0:
        if dp[i][j] == dp[i-1][j]:
            i -= 1
        elif dp[i][j] == dp[i][j-1]:
            j -= 1
        elif vals[j-1] in TEMPLATE[i-1] and dp[i][j] == dp[i-1][j-1] + 1:
            matched_pos[i-1] = (vals[j-1], cnts[j-1], lns[j-1])
            used_vals.add(j-1)
            i -= 1
            j -= 1
        else:
            i -= 1
    
    unused_vals = [(vals[k], cnts[k], lns[k]) for k in range(nv) if k not in used_vals]
    unused_idx = 0
    
    result = []
    match_count = 0
    for pos_idx in range(nt):
        if pos_idx in matched_pos:
            val, cnt, ln = matched_pos[pos_idx]
            result.append((val, cnt, True, ln))
            match_count += 1
        else:
            if unused_idx < len(unused_vals):
                val, cnt, ln = unused_vals[unused_idx]
                result.append((val, cnt, False, ln))
                unused_idx += 1
            else:
                result.append((None, 0, False, None))
    
    for k in range(1, nt):
        val_k, cnt_k, is_match_k, ln_k = result[k]
        if val_k is None:
            continue
        prev_val, prev_cnt, prev_match, prev_ln = result[k - 1]
        if prev_val is None:
            continue
        if not prev_match and prev_val in TEMPLATE[k - 1]:
            result[k - 1] = (prev_val, prev_cnt, True, prev_ln)
    
    return result, match_count, selected_orig, start


def generate_report():
    if not os.path.exists(INPUT_DIR):
        print(f"[ERROR] Input directory not found: {INPUT_DIR}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    subdirs = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
    if not subdirs:
        subdirs = ['']

    for subdir in subdirs:
        input_subdir = os.path.join(INPUT_DIR, subdir)
        report_subdir = os.path.join(OUTPUT_DIR, subdir)
        os.makedirs(report_subdir, exist_ok=True)

        files = []
        for root, dirs, filenames in os.walk(input_subdir):
            for fname in filenames:
                if not fname.endswith('.txt'):
                    continue
                files.append(os.path.join(root, fname))

        def natural_key(path):
            return [int(t) if t.isdigit() else t.lower()
                    for t in re.split(r'(\d+)', os.path.basename(path))]

        files.sort(key=natural_key)

        if not files:
            continue

        report_path = os.path.join(report_subdir, f"report_{subdir}.txt")
        print(f"[Report] Generating: {report_path}")

        # 先收集所有文件结果
        file_results = []
        file_stats = {}  # filename -> (raw行数, Total count, 排除x的Total count, +/-单列项count)
        total_matches = 0
        total_positions = 0
        total_time18 = 0    # 所有文件 Pos 上的行数(不含+/-单列项)累计
        total_target_rows = 0  # 所有文件 Pos 上的行数(含+/-单列项)累计
        total_raw_rows = 0     # 所有文件 raw rows 累计
        for filepath in files:
            filename = os.path.relpath(filepath, input_subdir)
            raw_values, raw_line_numbers = read_column_values(filepath, COLUMN_INDEX, trigger_col=3, trigger_val=1)
            if not raw_values:
                continue

            deduped_values, deduped_counts, deduped_line_numbers = deduplicate_with_count(raw_values, raw_line_numbers)
            deduped = list(zip(deduped_values, deduped_counts))
            matched, match_count, selected_orig, leading_ones = match_template(deduped, deduped_line_numbers)
            total_matches += match_count
            total_positions += 18
            mark_groups = count_any_col(filepath)
            total18 = calc_total_18(matched, deduped, deduped_line_numbers)
            time18 = calc_total_18(matched, deduped, deduped_line_numbers, exclude_x=True)
            signed_cnt = count_signed_standalone(deduped, matched, deduped_line_numbers)
            file_stats[filename] = (len(raw_values), total18, time18, signed_cnt)
            file_results.append((filename, raw_values, deduped, matched, match_count, selected_orig, mark_groups, deduped_line_numbers))
            total_time18 += time18
            total_target_rows += total18 + signed_cnt
            total_raw_rows += len(raw_values)

        # 计算综合准确率
        overall_accuracy = (total_matches / total_positions * 100) if total_positions > 0 else 0
        overall_accuracy_time = (total_time18 / total_raw_rows * 100) if total_raw_rows > 0 else 0
        overall_accuracy_target_time = (total_target_rows / total_raw_rows * 100) if total_raw_rows > 0 else 0

        # 构建新报告内容（行列表）
        new_lines = []
        new_lines.append("=" * 70)
        new_lines.append(f"Report for subdirectory: {subdir}")
        new_lines.append("=" * 70)
        new_lines.append("")
        new_lines.append(f">>> Overall Accuracy Base On Face: {overall_accuracy:.2f}% ({total_matches}/{total_positions})")
        new_lines.append(f">>> Overall Accuracy Based On Time: {overall_accuracy_time:.2f}% ({total_time18}/{total_raw_rows})")
        new_lines.append(f">>> Overall Accuracy Based On Target Time: {overall_accuracy_target_time:.2f}% ({total_target_rows}/{total_raw_rows})")
        new_lines.append(f">>> Total Files: {len(file_results)}")
        new_lines.append("")
        new_lines.append("File Matches:")
        for filename, _, _, _, match_count, _, mark_groups, _ in file_results:
            raw_cnt, total18, time18, signed_cnt = file_stats[filename]
            pct_face = (match_count / 18 * 100) if 18 else 0.0
            pct = (time18 / raw_cnt * 100) if raw_cnt else 0.0
            pct_with_sign = ((total18 + signed_cnt) / raw_cnt * 100) if raw_cnt else 0.0
            new_lines.append(f"  {filename}: {match_count}/18 {mark_groups}  {pct_face:.2f}%  {pct:.2f}%  {pct_with_sign:.2f}%")
        new_lines.append("")

        # 读取 def 文件，汇总每个参数的 min/max
        def_dir = os.path.join(INPUT_DIR, subdir)
        param_ranges = {}
        for fname in os.listdir(def_dir):
            if not fname.endswith(".def"):
                continue
            def_path = os.path.join(def_dir, fname)
            with open(def_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    vals = [x.strip() for x in v.split(",") if x.strip()]
                    for val in vals:
                        if val not in param_ranges.setdefault(k, []):
                            param_ranges[k].append(val)
        if param_ranges:
            new_lines.append("Def Parameters:")
            for k in param_ranges:
                nums = []
                for v in param_ranges[k]:
                    for part in re.split(r'[,\s]+', v):
                        part = part.strip()
                        m = re.match(r'^(-?[0-9.]+)\s*-\s*(-?[0-9.]+)', part)
                        if m:
                            nums.append(float(m.group(1)))
                            nums.append(float(m.group(2)))
                        else:
                            try:
                                nums.append(float(part))
                            except ValueError:
                                pass
                if nums:
                    vmin, vmax = min(nums), max(nums)
                    if vmin == vmax:
                        new_lines.append(f"  {k}: {vmin:g}")
                    else:
                        new_lines.append(f"  {k}: {vmin:g} ~ {vmax:g}")
            new_lines.append("")

        for filename, raw_values, deduped, matched, match_count, selected_orig, _, deduped_line_numbers in file_results:
            new_lines.append(f"File: {filename}")
            new_lines.append(f"  Raw rows: {len(raw_values)}")
            new_lines.append(f"  Match: {match_count}/18")

            # 构建 ln -> 位置信息 的映射
            pos_map = {}
            for i, (value, count, is_match, ln) in enumerate(matched, 1):
                if ln is not None:
                    pos_map[ln] = (i, value, count, is_match)

            # 输出规则：两个 Pos 之间夹的未分配值——
            #   第2遍扫描已分配的数（直接命中前后模板）不再参与 +/−：
            #     属于前一个 Pos 模板 -> 并入上一个 Pos 行（无符号，空格分隔）
            #     属于后一个 Pos 模板 -> '-' 前缀单列
            #   其余未分配值按成对关系标注：
            #     与前一个 Pos 模板成对（其 FACE_PAIR 在前一模板中） -> '+' 前缀单列
            #     与后一个 Pos 模板成对（其 FACE_PAIR 在后一模板中） -> '-' 前缀单列
            #     与前后模板均不成对                              -> 不带符号单列
            pos_main = {p: "--" for p in range(1, len(TEMPLATE) + 1)}
            for i, (value, count, is_match, ln) in enumerate(matched, 1):
                if ln is not None:
                    if value is None:
                        pos_main[i] = "--"
                    elif is_match:
                        pos_main[i] = f"({value},{ln})<{count}>"
                    else:
                        pos_main[i] = f"({value}x,{ln})<{count}>"

            pos_extra = {}
            standalone = {}
            first_pos_ln = min(pos_map.keys()) if pos_map else None
            prev_pos_num = None
            pending = []

            def classify_flush(next_pos_num):
                nonlocal pending
                if not pending:
                    return
                tpl_prev = TEMPLATE[prev_pos_num - 1] if prev_pos_num is not None else None
                tpl_next = TEMPLATE[next_pos_num - 1] if next_pos_num is not None else None
                items = []
                for val, cnt, oi in pending:
                    if tpl_prev is not None and val in tpl_prev:
                        pos_extra.setdefault(prev_pos_num, []).append(f"({val},{oi})<{cnt}>")
                    elif tpl_next is not None and val in tpl_next:
                        items.append(f"-({val},{oi})<{cnt}>")
                    else:
                        partner = FACE_PAIR.get(val)
                        if partner is not None and tpl_prev is not None and partner in tpl_prev:
                            items.append(f"+({val},{oi})<{cnt}>")
                        elif partner is not None and tpl_next is not None and partner in tpl_next:
                            items.append(f"-({val},{oi})<{cnt}>")
                        else:
                            items.append(f"({val},{oi})<{cnt}>")
                if items:
                    key = prev_pos_num if prev_pos_num is not None else 0
                    for wl in wrap_line('           ', items).split('\n'):
                        standalone.setdefault(key, []).append(wl)
                pending = []

            for i, (val, cnt) in enumerate(deduped):
                ln = deduped_line_numbers[i]
                if first_pos_ln is not None and ln < first_pos_ln:
                    continue
                if ln in pos_map:
                    pos_num, value, count, is_match = pos_map[ln]
                    classify_flush(pos_num)
                    prev_pos_num = pos_num
                else:
                    pending.append((val, cnt, ln))
            classify_flush(None)

            # 依 Pos 顺序输出：主行（主值 + 并入的补分值 + 模板），其后是该 Pos 的单列行
            for wl in standalone.get(0, []):
                new_lines.append(wl)
            for p in range(1, len(TEMPLATE) + 1):
                prefix = f'  Pos {p:2d}: '
                tpl = '{' + ', '.join(str(v) for v in TEMPLATE[p - 1]) + '}'
                items = [pos_main[p]] + pos_extra.get(p, []) + [tpl]
                line = prefix + ''.join(items)
                if len(line) <= MAX_LINE_LEN:
                    new_lines.append(line)
                else:
                    cur = prefix
                    for it in items:
                        cand = cur + it
                        if len(cand) > MAX_LINE_LEN and cur != prefix:
                            new_lines.append(cur)
                            cur = '           ' + it
                        else:
                            cur = cand
                    new_lines.append(cur)
                for wl in standalone.get(p, []):
                    new_lines.append(wl)
            # 18个Pos的count总和（主值 + 并入Pos行的补分值，含带x主值行），与明细 Pos 行展示一致
            new_lines.append(f"  18 Positions Total count: {file_stats[filename][1]} ({file_stats[filename][2]})")



        # 读取旧报告（如果存在），与新报告并排输出
        old_lines = []
        if os.path.exists(report_path):
            with open(report_path, 'r') as f:
                raw_lines = [line.rstrip('\n') for line in f.readlines()]
            # 如果已经是并排格式（含'|'分隔符），只取左列作为旧报告
            for line in raw_lines:
                sep_pos = line.rfind('|')
                if sep_pos >= 0:
                    old_lines.append(line[:sep_pos].rstrip())
                else:
                    old_lines.append(line)

        # 写入报告
        with open(report_path, 'w') as report:
            if old_lines:
                # 并排模式：旧报告在左，新报告在右
                max_old_len = max(len(line) for line in old_lines) if old_lines else 0
                col_width = max(max_old_len, 20) + 4
                max_lines = max(len(old_lines), len(new_lines))
                for i in range(max_lines):
                    old_part = old_lines[i] if i < len(old_lines) else ""
                    new_part = new_lines[i] if i < len(new_lines) else ""
                    report.write(f"{old_part:<{col_width}}| {new_part}\n")
            else:
                # 首次生成
                for line in new_lines:
                    report.write(line + '\n')


if __name__ == '__main__':
    print("=== Smart Toothbrush Report Generator (18-Pos) ===")
    generate_report()
    print("=== Done ===")