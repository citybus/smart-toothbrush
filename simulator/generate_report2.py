"""
Smart Toothbrush - Report Generator (12-Face mode)
"""

import argparse
import os
import re

COLUMN_INDEX = 15
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output')
SUBDIR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'input')
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'report')

TEMPLATE = [
    [5,11],
    [6,12],
    {3,9},
    {4,10},
    (13,), (14,), (15,), (16,)
]

TIME_ACCURACY_THRESHOLD = 0

MAX_LINE_LEN = 70


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


def strip_parallel_col(line):
    """剥离并排格式的所有右列，只保留第一列"""
    sep_pos = line.find('|')
    if sep_pos >= 0:
        return line[:sep_pos].rstrip()
    return line


def read_backup_side(backup_file):
    """按当前写入模式读取备份同一侧的内容行列表。
    右模式（最后一非空行以'='开头）取'|'右列，否则取左列。
    左右是两次独立计算，只允许同侧（上下）继承。"""
    with open(backup_file, 'r', encoding='utf-8') as f:
        old_lines = [line.rstrip('\n') for line in f]
    last_non_space = ''
    for line in reversed(old_lines):
        if line and line[0] != ' ':
            last_non_space = line
            break
    is_right = last_non_space.startswith('=')
    side_lines = []
    for line in old_lines:
        if is_right:
            sep_pos = line.rfind('|')
            side_lines.append(line[sep_pos + 1:] if sep_pos >= 0 else '')
        else:
            side_lines.append(strip_parallel_col(line))
    return side_lines


def count_any_col(filepath, target_col=22, trigger_col=3, trigger_val=1):
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
                if trigger_col is not None and 1 <= trigger_col <= len(parts):
                    try:
                        if int(parts[trigger_col - 1]) == trigger_val:
                            triggered = True
                    except ValueError:
                        continue
                continue
            if 1 <= target_col <= len(parts):
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
                if trigger_col is not None and 1 <= trigger_col <= len(parts):
                    try:
                        if int(parts[trigger_col - 1]) == trigger_val:
                            triggered = True
                    except ValueError:
                        continue
                continue
            if 1 <= col_index <= len(parts):
                try:
                    values.append(int(parts[col_index - 1]))
                    line_numbers.append(line_num)
                except ValueError:
                    continue
    return values, line_numbers


def deduplicate_with_count(values, line_numbers):
    if not values:
        return [], [], []
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


def read_v15_ones(filepath):
    """返回 V15==1 的行号集合，V15 = 第28列"""
    result = set()
    line_num = 0
    with open(filepath, 'r') as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) >= 28:
                try:
                    if int(float(parts[27])) == 1:
                        result.add(line_num)
                except ValueError:
                    pass
    return result


def first_v15_line(v15_ones, ln, cnt):
    """段 ln..ln+cnt-1 内第一个 V15==1 的行号，没有则返回 None"""
    if v15_ones is None:
        return None
    for r in range(ln, ln + cnt):
        if r in v15_ones:
            return r
    return None


def fmt_face_item(val, ln, cnt, tpl, v15_ones=None):
    """stage2 时格式为 (val,ln,V15行号)<cnt>{tpl}，否则 (val,ln)<cnt>{tpl}"""
    v15_ln = first_v15_line(v15_ones, ln, cnt)
    if v15_ln is None:
        return f"({val},{ln})<{cnt}>{tpl}"
    return f"({val},{ln},{v15_ln})<{cnt}>{tpl}"


def classify_faces(deduped_with_count, deduped_line_numbers, v15_ones=None):
    """把每个deduped值归类到12个Face中，返回每个Face的值列表（cnt<100的跳过）
    v15_ones 非None时：段级过滤，段的行范围内无V15==1的段直接剔除
    [] 包含的face不要求V15=1，跳过该过滤"""
    face_values = [[] for _ in range(len(TEMPLATE))]
    for i, (val, cnt) in enumerate(deduped_with_count):
        ln = deduped_line_numbers[i]
        if cnt < 100:
            continue
        for fi, tpl in enumerate(TEMPLATE):
            if val in tpl:
                face_values[fi].append((val, ln, cnt))
                break
    if v15_ones is not None:
        for fi, fv in enumerate(face_values):
            if isinstance(TEMPLATE[fi], list):
                continue  # [] 包含的 face 不要求 V15=1
            face_values[fi] = [(val, ln, cnt) for val, ln, cnt in fv
                               if any(r in v15_ones for r in range(ln, ln + cnt))]
    return face_values


def generate_report(stage1=False, stage2=False, subdir_filter=None):
    if not os.path.exists(INPUT_DIR):
        print(f"[ERROR] Input directory not found: {INPUT_DIR}")
        return
    if not os.path.exists(SUBDIR_DIR):
        print(f"[ERROR] Input directory not found: {SUBDIR_DIR}")
        return

    global TEMPLATE
    if stage2:
        TEMPLATE = [t for t in TEMPLATE if isinstance(t, (set, list))]
    else:
        TEMPLATE = [t for t in TEMPLATE if isinstance(t, tuple)]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    subdirs = [d for d in os.listdir(SUBDIR_DIR) if os.path.isdir(os.path.join(SUBDIR_DIR, d))]
    if subdir_filter:
        if subdir_filter not in subdirs:
            print(f"[ERROR] input 下没有子目录: {subdir_filter}")
            return
        subdirs = [subdir_filter]
    elif not subdirs:
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

        file_results = []
        file_stats = {}
        total_matches = 0
        total_faces = 0
        total_time12 = 0
        total_raw_rows = 0
        v15_ones_map = {}  # filename -> {V15==1 的行号集合}
        for filepath in files:
            filename = os.path.relpath(filepath, input_subdir)
            raw_values, raw_line_numbers = read_column_values(filepath, COLUMN_INDEX, trigger_col=3, trigger_val=1)
            if not raw_values:
                continue

            deduped_values, deduped_counts, deduped_line_numbers = deduplicate_with_count(raw_values, raw_line_numbers)
            deduped = list(zip(deduped_values, deduped_counts))
            v15_ones = read_v15_ones(filepath) if stage2 else None
            v15_ones_map[filename] = v15_ones
            face_values = classify_faces(deduped, deduped_line_numbers, v15_ones)

            match_count = sum(1 for fv in face_values if fv)
            time12 = sum(cnt for fv in face_values for _, _, cnt in fv)
            mark_groups = count_any_col(filepath)
            time_pct = (time12 / len(raw_values) * 100) if raw_values else 0.0

            total_matches += match_count
            total_faces += len(TEMPLATE)
            total_time12 += time12
            total_raw_rows += len(raw_values)

            file_stats[filename] = (len(raw_values), time12, mark_groups, time_pct)
            file_results.append((filename, raw_values, deduped, face_values, match_count, deduped_line_numbers))

        overall_accuracy = (total_matches / total_faces * 100) if total_faces > 0 else 0
        overall_time_pct = (total_time12 / total_raw_rows * 100) if total_raw_rows > 0 else 0

        stage1_thresholds = {}
        stage1_main_faces = {}
        if stage1:
            saved_main_clusters = {}
            for i in range(len(file_results)):
                fn, rv, dv, fv, mc, dln = file_results[i]
                if mc == 0:
                    continue
                all_faces = []
                for fi_fv in fv:
                    for val, ln, cnt in fi_fv:
                        all_faces.append((val, ln, cnt))
                all_faces.sort(key=lambda x: x[1])
                if len(all_faces) < 2:
                    continue
                lns = [ln for _, ln, _ in all_faces]
                span = lns[-1] - lns[0]
                max_gap = max(lns[j] - lns[j-1] for j in range(1, len(lns)))
                threshold = min(max(span * 2, max_gap, 1000), 2000)
                stage1_thresholds[fn] = threshold
                prev_main = saved_main_clusters.get(fn)
                if prev_main is None:
                    backup_file = os.path.join(report_subdir, fn)
                    if os.path.exists(backup_file):
                        last_faces = []
                        last_thr = None
                        cur_faces = []
                        cur_thr = None
                        for bline in read_backup_side(backup_file):
                            bline = bline.rstrip()
                            if 'Stage1 Threshold:' in bline:
                                cur_thr = int(bline.split(':')[1].strip())
                                cur_faces = []
                            elif 'Main Face:' in bline:
                                m = re.search(r'val=(-?\d+),\s*ln=(-?\d+),\s*cnt=(-?\d+)', bline)
                                if m:
                                    cur_faces.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
                            elif bline.startswith('====') or bline.startswith('  Face'):
                                if cur_faces:
                                    last_faces = cur_faces[:]
                                    last_thr = cur_thr
                                cur_faces = []
                        if cur_faces:
                            last_faces = cur_faces[:]
                            last_thr = cur_thr
                        if last_faces and last_thr:
                            prev_main = [(v, l, c, l + c / 2, last_thr) for v, l, c in last_faces]
                            saved_main_clusters[fn] = prev_main
                            print(f"[stage1] {fn} 从备份读取主集群{len(prev_main)}个面")
                newsaved = []
                prev_time_pct = None
                backup_file = os.path.join(report_subdir, fn)
                if os.path.exists(backup_file):
                    for bline in read_backup_side(backup_file):
                        bline = bline.rstrip()
                        if 'Time Accuracy:' in bline:
                            tm = re.search(r'(-?[0-9.]+)%', bline)
                            if tm:
                                prev_time_pct = float(tm.group(1))
                if prev_main is not None:
                    prev_lns = set(mln for _, mln, _, _, _ in prev_main)
                    prev_threshold = prev_main[0][4]
                    new_total = 0
                    for val, ln, cnt in all_faces:
                        if any(abs(ln - m) <= prev_threshold for m in prev_lns):
                            new_total += cnt
                            newsaved.append((val, ln, cnt, ln + cnt / 2, prev_threshold))
                        else:
                            new_total -= cnt
                    stage1_main_faces[fn] = [(v, l, c, m) for v, l, c, m, _ in newsaved]
                    raw_cnt, time12, mark_groups, time_pct = file_stats[fn]
                    if prev_time_pct is not None and prev_time_pct < TIME_ACCURACY_THRESHOLD:
                        new_time_pct = prev_time_pct
                    else:
                        new_time_pct = (new_total / raw_cnt * 100) if raw_cnt else 0.0
                    file_stats[fn] = (raw_cnt, new_total, mark_groups, new_time_pct)
                    face_str = ' '.join(f"({v},{l},{c})" for v, l, c, m in stage1_main_faces[fn])
                    print(f"[stage1] {fn} 旧主集群{len(prev_main)}个面，匹配{len(stage1_main_faces[fn])}个面 {face_str} Time={new_time_pct:.2f}% (total={new_total})")
                else:
                    main_lns = set()
                    main_formed = False
                    non_main_streak = 0
                    for val, ln, cnt in all_faces:
                        if not main_formed:
                            if any(abs(ln - m) <= threshold for m in main_lns):
                                main_lns.add(ln)
                                if len(main_lns) >= 2:
                                    main_formed = True
                                non_main_streak = 0
                            elif main_lns:
                                non_main_streak += 1
                            else:
                                main_lns.add(ln)
                        else:
                            if any(abs(ln - m) <= threshold for m in main_lns):
                                main_lns.add(ln)
                                non_main_streak = 0
                            else:
                                non_main_streak += 1
                    if main_formed and len(main_lns) >= 2:
                        new_total = 0
                        for val, ln, cnt in all_faces:
                            if ln in main_lns:
                                new_total += cnt
                            else:
                                new_total -= cnt
                        newsaved = [(val, ln, cnt, ln + cnt / 2, threshold) for val, ln, cnt in all_faces if ln in main_lns]
                        stage1_main_faces[fn] = [(v, l, c, m) for v, l, c, m, _ in newsaved]
                        raw_cnt, time12, mark_groups, time_pct = file_stats[fn]
                        if prev_time_pct is not None and prev_time_pct < TIME_ACCURACY_THRESHOLD:
                            new_time_pct = prev_time_pct
                        else:
                            new_time_pct = (new_total / raw_cnt * 100) if raw_cnt else 0.0
                        file_stats[fn] = (raw_cnt, new_total, mark_groups, new_time_pct)
                        face_str = ' '.join(f"({v},{l},{c})" for v, l, c, m in stage1_main_faces[fn])
                        print(f"[stage1] {fn} 创建主集群{len(newsaved)}个面 {face_str} Time={new_time_pct:.2f}% (total={new_total})")
                if newsaved:
                    saved_main_clusters[fn] = newsaved
            total_matches = sum(mc for _, _, _, _, mc, _ in file_results)
            overall_accuracy = (total_matches / total_faces * 100) if total_faces > 0 else 0
            total_time12 = sum(fs[1] for fs in file_stats.values())
            overall_time_pct = (total_time12 / total_raw_rows * 100) if total_raw_rows > 0 else 0


        new_lines = []
        new_lines.append("=" * 70)
        new_lines.append(f"Report for subdirectory: {subdir}")
        new_lines.append("=" * 70)
        new_lines.append("")
        new_lines.append(f">>> Overall Accuracy Base On Face: {overall_accuracy:.2f}% ({total_matches}/{total_faces})")
        new_lines.append(f">>> Overall Accuracy Based On Time: {overall_time_pct:.2f}% ({total_time12}/{total_raw_rows})")
        new_lines.append(f">>> Total Files: {len(file_results)}")
        new_lines.append("")
        new_lines.append("File Matches:")
        for filename, _, _, _, match_count, _ in file_results:
            raw_cnt, time12, mark_groups, time_pct = file_stats[filename]
            pct_face = (match_count / len(TEMPLATE) * 100) if TEMPLATE else 0.0
            new_lines.append(f"  {filename}: {match_count}/{len(TEMPLATE)} {mark_groups}  {pct_face:.2f}%  {time_pct:.2f}%")
        new_lines.append("")

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
                    param_ranges.setdefault(k, []).extend(vals)
        if param_ranges:
            new_lines.append("Def Parameters:")
            for k in param_ranges:
                nums = []
                for v in param_ranges[k]:
                    # 解析范围格式 "12.0-28.0:1.0" 和普通数值
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

        for filename, raw_values, deduped, face_values, match_count, deduped_line_numbers in file_results:
            time12 = sum(cnt for fv in face_values for _, _, cnt in fv)
            new_lines.append(f"File: {filename}")
            new_lines.append(f"  Raw rows: {len(raw_values)}")
            new_lines.append(f"  Match: {match_count}/{len(TEMPLATE)}")

            all_items = []
            v15_set = v15_ones_map.get(filename)
            for fi in range(len(TEMPLATE)):
                tpl = '{' + ', '.join(str(v) for v in TEMPLATE[fi]) + '}'
                fv = face_values[fi]
                if fv:
                    for val, ln, cnt in fv:
                        all_items.append((ln, fi, fmt_face_item(val, ln, cnt, tpl, v15_set)))
            all_items.sort(key=lambda x: x[0])

            merged = []
            for ln, fi, item_str in all_items:
                if merged and merged[-1][1] == fi:
                    merged[-1][2].append(item_str)
                else:
                    merged.append((ln, fi, [item_str]))
            for ln, fi, items in merged:
                prefix = f'  Face {fi+1:2d}: '
                for wl in wrap_line(prefix, items).split('\n'):
                    new_lines.append(wl)

            new_lines.append(f"  12 Faces Total count: {time12}")
            new_lines.append("")

        old_lines = []
        if os.path.exists(report_path):
            with open(report_path, 'r') as f:
                raw_lines = [line.rstrip('\n') for line in f.readlines()]
            for line in raw_lines:
                sep_pos = line.rfind('|')
                if sep_pos >= 0:
                    old_lines.append(line[:sep_pos].rstrip())
                else:
                    old_lines.append(line)

        # 构建报告内容
        lines = []
        if old_lines:
            max_old_len = max(len(line) for line in old_lines) if old_lines else 0
            col_width = max(max_old_len, 20) + 4
            max_lines = max(len(old_lines), len(new_lines))
            for i in range(max_lines):
                old_part = old_lines[i] if i < len(old_lines) else ""
                new_part = new_lines[i] if i < len(new_lines) else ""
                lines.append(f"{old_part:<{col_width}}| {new_part}")
        else:
            lines = new_lines

        with open(report_path, 'w') as report:
            for line in lines:
                report.write(line + '\n')

        # 每个输入文件的结果追加到自己的文件
        for filename, raw_values, deduped, face_values, match_count, deduped_line_numbers in file_results:
            raw_cnt, time12, mark_groups, time_pct = file_stats[filename]
            backup_path = os.path.join(report_subdir, filename)

            # 构建新内容
            new_lines = []
            new_lines.append("=" * 50)
            # 写入当前参数
            # 找对应的 .def 文件
            base = filename.replace('.txt', '.')
            def_path = None
            for df in os.listdir(input_subdir):
                if df.startswith(base) and df.endswith('.def'):
                    def_path = os.path.join(input_subdir, df)
                    break
            if def_path and os.path.exists(def_path):
                with open(def_path, 'r', encoding='utf-8') as df:
                    for line in df:
                        line = line.strip()
                        if line:
                            new_lines.append(f"  {line}")
            new_lines.append(f"Face Accuracy: {match_count}/{len(TEMPLATE)} ({match_count/len(TEMPLATE)*100:.2f}%)")
            new_lines.append(f"Time Accuracy: {time_pct:.2f}%")
            if filename in stage1_thresholds:
                new_lines.append(f"Stage1 Threshold: {stage1_thresholds[filename]}")
                if filename in stage1_main_faces:
                    for v, l, c, m in stage1_main_faces[filename]:
                        new_lines.append(f"  Main Face: val={v}, ln={l}, cnt={c}, mid={m:.0f}")
            all_items = []
            v15_set = v15_ones_map.get(filename)
            for fi in range(len(TEMPLATE)):
                tpl = '{' + ', '.join(str(v) for v in TEMPLATE[fi]) + '}'
                fv = face_values[fi]
                if fv:
                    for val, ln, cnt in fv:
                        all_items.append((ln, fi, fmt_face_item(val, ln, cnt, tpl, v15_set)))
            all_items.sort(key=lambda x: x[0])

            merged = []
            for ln, fi, item_str in all_items:
                if merged and merged[-1][1] == fi:
                    merged[-1][2].append(item_str)
                else:
                    merged.append((ln, fi, [item_str]))
            for ln, fi, items in merged:
                prefix = f'  Face {fi+1:2d}: '
                for wl in wrap_line(prefix, items).split('\n'):
                    new_lines.append(wl)
            new_lines.append(f"  Total count: {time12}")

            # 判断写入左侧还是右侧
            try:
                old_lines = []
                if os.path.exists(backup_path):
                    with open(backup_path, 'r', encoding='utf-8') as f:
                        old_lines = [line.rstrip('\n') for line in f.readlines()]

                last_non_space = ''
                for line in reversed(old_lines):
                    if line and line[0] != ' ':
                        last_non_space = line
                        break
                is_right_mode = last_non_space.startswith('=')

                if is_right_mode:
                    old_left = []
                    old_right = []
                    for line in old_lines:
                        sep_pos = line.rfind('|')
                        if sep_pos >= 0:
                            old_left.append(line[:sep_pos].rstrip())
                            old_right.append(line[sep_pos+1:])
                        else:
                            old_left.append(line)
                            old_right.append('')

                    insert_pos = 0
                    for i in range(len(old_right)):
                        if not old_right[i].strip():
                            insert_pos = i
                            break
                    else:
                        insert_pos = len(old_right)

                    for i, nl in enumerate(new_lines):
                        pos = insert_pos + i
                        if pos < len(old_right):
                            old_right[pos] = nl
                        else:
                            old_right.append(nl)

                    max_len = max(len(old_left), len(old_right))
                    while len(old_left) < max_len:
                        old_left.append('')
                    while len(old_right) < max_len:
                        old_right.append('')

                    with open(backup_path, 'w', encoding='utf-8') as f:
                        max_left_len = max((len(line) for line in old_left), default=20)
                        col_width = max(max_left_len, 20) + 4
                        for i in range(max_len):
                            left_part = old_left[i]
                            right_part = old_right[i] if i < len(old_right) else ""
                            if i == len(old_left) - 1 and left_part.strip() == '=' * 50:
                                f.write(left_part + "\n")
                            else:
                                f.write(f"{left_part:<{col_width}}|{right_part}\n")
                else:
                    # 左侧模式：直接追加新内容到文件末尾
                    with open(backup_path, 'a', encoding='utf-8') as f:
                        for line in new_lines:
                            f.write(line + '\n')
            except Exception as e:
                print(f"[Report] Backup写入失败 {backup_path}: {e}")
            print(f"[Report] Backup: {backup_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1", action="store_true")
    parser.add_argument("--stage2", action="store_true")
    parser.add_argument("--subdir", help="只生成该子目录的报告（默认全部）")
    a = parser.parse_args()
    if not (a.stage1 or a.stage2):
        print("请指定运行阶段: --stage1  或  --stage2")
        exit(1)
    print("=== Smart Toothbrush Report Generator (12-Face) ===")
    generate_report(stage1=a.stage1, stage2=a.stage2, subdir_filter=a.subdir)
    print("=== Done ===")
