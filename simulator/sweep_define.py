r"""
sweep_define.py - 扫描某个宏的取值，使 accuracy 最大。

模式：
  默认: 整体模式，扫描所有文件，找 overall 最优值
  --per-file: 逐文件模式，为每个文件找各自的最优值

整体模式流程（原有）：
  1) 改 alg_toothbrush.c 中的宏值 + jni\build.bat 编译单个 DLL
  2) simulator\run.bat 跑全部文件
  3) generate_report.py 生成报告
  4) 读取 Overall Accuracy

Per-file 模式流程：
  1) 更新 input/<subdir>/ 下所有 .def 文件中当前宏的值
  2) jni\build_all.bat 编译 per-file DLL
  3) simulator\build_all.bat 编译 per-file EXE
  4) simulator\run_all.bat 跑 per-file 仿真
  5) generate_report.py 生成报告
  6) 读取每个文件的 accuracy
"""

import argparse
import csv
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "jni", "alg_toothbrush.c")
JNI_BUILD = os.path.join(ROOT, "jni", "build.bat")
JNI_BUILD_ALL = os.path.join(ROOT, "jni", "build_all.bat")
RUN_BAT = os.path.join(HERE, "run.bat")
SIM_BUILD_ALL = os.path.join(HERE, "build_all.bat")
SIM_RUN_ALL = os.path.join(HERE, "run_all.bat")
REPORT_PY = os.path.join(HERE, "generate_report.py")
REPORT2_PY = os.path.join(HERE, "generate_report2.py")

TARGET = "time"  # 可选: "face" | "time"
SECONDARY = "time" if TARGET == "face" else "face"  # 第二目标

ACC_RE_FACE = re.compile(
    r">>>\s*Overall Accuracy(?:\s+Base On Face)?:\s*([0-9.]+)%\s*\((\d+)\s*/\s*(\d+)\)")
ACC_RE_TIME = re.compile(
    r">>>\s*Overall Accuracy Based On Time:\s*([0-9.]+)%\s*\((\d+)\s*/\s*(\d+)\)")
ACC_RE = ACC_RE_TIME if str(TARGET).strip().lower() == "time" else ACC_RE_FACE


def run_step(cmd, cwd=None):
    p = subprocess.run(
        cmd, cwd=cwd, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    out = p.stdout or ""
    ok = p.returncode == 0 and "Build FAILED" not in out
    return ok, out


def get_define_value(src_text, name):
    m = re.search(
        r'^(\s*#\s*define\s+' + re.escape(name) + r'\s+)(\S+)([^\r\n]*)',
        src_text, re.MULTILINE)
    if not m:
        raise SystemExit(f"[ERROR] 在源码中找不到 #define {name}: {SRC}")
    return m.group(2)


def set_define_value(src_text, name, new_token):
    pat = re.compile(
        r'^(\s*#\s*define\s+' + re.escape(name) + r'\s+)(\S+)([^\r\n]*)',
        re.MULTILINE)
    n = 0
    def repl(m):
        nonlocal n
        n += 1
        return m.group(1) + new_token + m.group(3)
    new_text = pat.sub(repl, src_text)
    return new_text, n


def fmt(v, is_float):
    if is_float:
        return "%g" % v
    return str(int(round(v)))


def compress_values(vals):
    nums = []
    for v in vals:
        try:
            nums.append(float(v))
        except ValueError:
            return ",".join(vals)
    nums.sort()
    if len(nums) <= 1:
        return str(nums[0]) if nums else ""
    result = []
    i = 0
    while i < len(nums):
        if i + 1 >= len(nums):
            result.append(str(nums[i]))
            break
        step = round(nums[i+1] - nums[i], 9)
        end = i + 1
        while end + 1 < len(nums) and abs(round(nums[end+1] - nums[end], 9) - step) < 1e-9:
            end += 1
        if end - i >= 2:
            result.append(f"{nums[i]}-{nums[end]}:{step}")
        else:
            result.append(str(nums[i]))
            if i + 1 < len(nums) and end == i + 1:
                result.append(str(nums[i+1]))
        i = end + 1
    return ",".join(result)


def read_accuracy(report_file):
    if not os.path.exists(report_file):
        return None
    with open(report_file, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    matches = ACC_RE.findall(text)
    if not matches:
        return None
    acc, m, n = matches[-1]
    return float(acc), int(m), int(n)


def read_per_file_accuracy(report_file, metric="face"):
    if not os.path.exists(report_file):
        return {}
    col_idx = {"face": 3, "time": 4, "target_time": 5}.get(metric, 3)
    results = {}
    with open(report_file, "r", encoding="utf-8", errors="replace") as f:
        in_section = False
        for line in f:
            stripped = line.strip()
            if stripped.startswith("File Matches:"):
                in_section = True
                continue
            if in_section:
                if not stripped:
                    if results:
                        break
                    continue
                parts = stripped.split()
                if len(parts) >= 5 and re.match(r'.*/\d+', parts[1]):
                    fname = parts[0].rstrip(':')
                    pcts = [p for p in parts[2:] if p.endswith('%')]
                    if len(pcts) >= col_idx - 2:
                        acc = float(pcts[col_idx - 3].rstrip('%'))
                        results[fname] = acc
    return results


# ========== Per-file 模式 ==========

def init_def_files(def_dir, input_dir, src_text, macros, target_macro=None):
    os.makedirs(def_dir, exist_ok=True)
    txt_files = [f for f in os.listdir(input_dir) if f.endswith(".txt")]
    missing_target = False
    for txt_file in txt_files:
        def_path = os.path.join(def_dir, txt_file.replace(".txt", f".{TARGET}.def"))
        lines = {}
        if os.path.exists(def_path):
            with open(def_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k = line.split("=", 1)[0]
                        lines[k] = line
        else:
            print(f"[sweep] {txt_file} 无def文件 (以代码初始值作为起点)")
        for macro in macros:
            if macro not in lines:
                default_val = get_define_value(src_text, macro)
                if default_val:
                    clean_val = default_val.rstrip("f")
                    lines[macro] = f"{macro}={clean_val}"
                    if macro == target_macro:
                        missing_target = True
        with open(def_path, "w", encoding="utf-8") as f:
            for v in lines.values():
                f.write(v + "\n")
    if missing_target:
        print(f"[sweep] 宏 {target_macro} 无def文件 (以代码初始值作为起点)")


def update_def_files(def_dir, input_dir, macro, value):
    txt_files = [f for f in os.listdir(input_dir) if f.endswith(".txt")]
    for txt_file in txt_files:
        def_path = os.path.join(def_dir, txt_file.replace(".txt", f".{TARGET}.def"))
        lines = {}
        if os.path.exists(def_path):
            with open(def_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k = line.split("=", 1)[0]
                        lines[k] = line
        lines[macro] = f"{macro}={value}"
        with open(def_path, "w", encoding="utf-8") as f:
            for v in lines.values():
                f.write(v + "\n")


def sweep_per_file(args, vals):
    """Per-file 模式：为每个文件找各自的最优值"""
    input_dir = os.path.join(ROOT, "input", args.subdir)
    def_dir = os.path.join(ROOT, "output", args.subdir)
    report_dir = os.path.join(ROOT, "report", args.subdir)
    report_file = os.path.join(report_dir, f"report_{args.subdir}.txt")

    src_path = os.path.join(ROOT, "jni", "alg_toothbrush.c")
    with open(src_path, "r", encoding="utf-8") as f:
        src_text = f.read()

    sweep_def = os.path.join(HERE, "sweep_define.def")
    all_macros = []
    if os.path.exists(sweep_def):
        with open(sweep_def, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if parts:
                    all_macros.append(parts[0])

    print(f"[sweep] 宏 {args.define} 候选 {len(vals)} 个值: {[fmt(v, args.is_float) for v in vals]}")
    print(f"[sweep] 输入目录: {input_dir}")
    print("-" * 72)

    init_def_files(def_dir, input_dir, src_text, all_macros, target_macro=args.define)

    per_file_best = {}
    results = []

    for idx, val in enumerate(vals, 1):
        token = fmt(val, args.is_float)
        t0 = time.time()

        update_def_files(def_dir, input_dir, args.define, token)

        ok, out = run_step(f'"{JNI_BUILD_ALL}"')
        if not ok:
            print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  DLL 编译失败，跳过")
            results.append((token, None, time.time() - t0))
            continue

        ok, out = run_step(f'"{SIM_BUILD_ALL}"')
        if not ok:
            print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  EXE 编译失败，跳过")
            results.append((token, None, time.time() - t0))
            continue

        ok, out = run_step(f'"{SIM_RUN_ALL}"')
        if not ok:
            print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  仿真运行失败，跳过")
            results.append((token, None, time.time() - t0))
            continue

        for _attempt in range(6):
            try:
                if os.path.exists(report_file):
                    os.remove(report_file)
                break
            except PermissionError:
                time.sleep(0.5)

        stage_args = ""
        if args.stage1: stage_args += " --stage1"
        if args.stage2: stage_args += " --stage2"
        if args.stage3: stage_args += " --stage3"
        report_script = REPORT2_PY if stage_args else REPORT_PY
        ok, out = run_step(f'"{sys.executable}" "{report_script}"{stage_args}', cwd=HERE)
        if not ok:
            print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  报告生成失败，跳过")
            results.append((token, None, time.time() - t0))
            continue

        per_file_acc = read_per_file_accuracy(report_file, metric=TARGET)
        per_file_acc2 = read_per_file_accuracy(report_file, metric=SECONDARY)
        elapsed = time.time() - t0

        for fname in list(per_file_acc.keys()):
            if per_file_acc.get(fname, 0) == 0 or per_file_acc2.get(fname, 0) == 0:
                del per_file_acc[fname]
                per_file_acc2.pop(fname, None)

        avg_acc = sum(per_file_acc.values()) / len(per_file_acc) if per_file_acc else 0
        results.append((token, avg_acc, elapsed))

        for fname, facc in per_file_acc.items():
            facc2 = per_file_acc2.get(fname, 0)
            if fname not in per_file_best:
                per_file_best[fname] = (facc, facc2, [token])
            elif facc > per_file_best[fname][0]:
                per_file_best[fname] = (facc, facc2, [token])
            elif abs(facc - per_file_best[fname][0]) < 1e-9:
                if facc2 > per_file_best[fname][1]:
                    per_file_best[fname] = (facc, facc2, [token])
                elif abs(facc2 - per_file_best[fname][1]) < 1e-9:
                    per_file_best[fname][2].append(token)

        sorted_files = sorted(per_file_acc.keys())
        for i, fname in enumerate(sorted_files):
            best_acc_f, best_acc2_f, best_tok_f = per_file_best[fname]
            cur_acc = per_file_acc[fname]
            cur_acc2 = per_file_acc2.get(fname, 0)
            is_best = " *" if abs(cur_acc - best_acc_f) < 1e-9 else ""
            if i == 0:
                print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  {elapsed:.1f}s  {fname}: {TARGET}={cur_acc:.1f}% {SECONDARY}={cur_acc2:.1f}% (best={best_acc_f:.1f}%){is_best}")
            else:
                print(f"         {fname}: {TARGET}={cur_acc:.1f}% {SECONDARY}={cur_acc2:.1f}% (best={best_acc_f:.1f}%){is_best}")

    csv_path = os.path.join(HERE, f"sweep_{args.define}_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["value", "avg_accuracy_pct", "elapsed_s"])
        for token, avg_acc, el in results:
            w.writerow([token, "" if avg_acc is None else f"{avg_acc:.2f}", f"{el:.1f}"])
    print(f"\n[sweep] 扫描表已保存: {csv_path}")

    print("=" * 72)
    print(f"[sweep] Per-file 最优 {args.define}:")
    for fname in sorted(per_file_best.keys()):
        best_acc_f, best_acc2_f, best_tok_f = per_file_best[fname]
        best_str_f = compress_values(best_tok_f)
        print(f"  {fname}: {args.define}={best_str_f}  {TARGET}={best_acc_f:.2f}%  {SECONDARY}={best_acc2_f:.2f}%")

    for fname in sorted(per_file_best.keys()):
        best_acc_f, best_acc2_f, best_tok_f = per_file_best[fname]
        best_str_f = compress_values(best_tok_f)
        def_path = os.path.join(def_dir, fname.replace(".txt", f".{TARGET}.def"))
        lines = {}
        if os.path.exists(def_path):
            with open(def_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k = line.split("=", 1)[0]
                        lines[k] = line
        lines[args.define] = f"{args.define}={best_str_f}"
        with open(def_path, "w", encoding="utf-8") as f:
            for v in lines.values():
                f.write(v + "\n")
    print(f"[sweep] 最优参数已写入: {def_dir}")
    return 0


# ========== 整体模式（原有）==========

def sweep_overall(args, vals):
    """整体模式：找 overall 最优值"""
    with open(SRC, "r", encoding="utf-8") as f:
        orig_text = f.read()
    true_orig = orig_text
    orig_token = get_define_value(orig_text, args.define)
    print(f"[sweep] 宏 {args.define} 代码原始值 = {orig_token}")

    output_dir = os.path.join(ROOT, "output", args.subdir)
    input_dir = os.path.join(ROOT, "input", args.subdir)

    def_token = None
    all_def_params = {}
    for fname in os.listdir(output_dir):
        if not fname.endswith(".txt"):
            continue
        def_path = os.path.join(output_dir, fname.replace(".txt", f".{TARGET}.def"))
        if os.path.exists(def_path):
            with open(def_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        raw = v.strip().split(",")[0]
                        rm = re.match(r'^(-?[0-9.]+)-(-?[0-9.]+):(-?[0-9.]+)$', raw)
                        if rm:
                            raw = rm.group(1)
                        try:
                            fv = float(raw)
                            val = str(int(fv)) if fv == int(fv) else raw
                        except ValueError:
                            val = raw
                        all_def_params[k] = val
                        if k == args.define:
                            def_token = val
            if def_token is not None:
                break

    start_token = orig_token
    if def_token is not None:
        start_token = def_token
        print(f"[sweep] 宏 {args.define} def值 = {def_token} (以def文件作为起点)")
        new_text = orig_text
        for k, v in all_def_params.items():
            new_text, n = set_define_value(new_text, k, v)
            if n > 0:
                print(f"[sweep] 已加载 {k} = {v}")
        with open(SRC, "w", encoding="utf-8") as f:
            f.write(new_text)
        orig_text = new_text
    else:
        print(f"[sweep] 宏 {args.define} 无def文件 (以代码初始值作为起点)")

    print(f"[sweep] 候选 {len(vals)} 个值: {[fmt(v, args.is_float) for v in vals]}")
    print(f"[sweep] 目标报告: report/{args.subdir}/report_{args.subdir}.txt")
    print("-" * 72)

    stage_args = ""
    if args.stage1: stage_args += " --stage1"
    if args.stage2: stage_args += " --stage2"
    if args.stage3: stage_args += " --stage3"
    report_script = REPORT2_PY if stage_args else REPORT_PY

    report_dir = os.path.join(ROOT, "report", args.subdir)
    report_file = os.path.join(report_dir, f"report_{args.subdir}.txt")

    # 用 def_token 值生成起点报告
    if def_token is not None:
        with open(SRC, "w", encoding="utf-8") as f:
            f.write(orig_text)
        ok, out = run_step(f'"{JNI_BUILD}"')
        if ok and "successful" in out:
            ok, out = run_step(f'"{RUN_BAT}"')
            if ok and "Done" in out:
                for _attempt in range(6):
                    try:
                        if os.path.exists(report_file):
                            os.remove(report_file)
                        break
                    except PermissionError:
                        time.sleep(0.5)
                ok, out = run_step(f'"{sys.executable}" "{report_script}"{stage_args}', cwd=HERE)
                r = read_accuracy(report_file)
                if r:
                    base_acc, base_m, base_n = r
                    print(f"[sweep] 起点值 {def_token} Accuracy = {base_acc:.2f}% ({base_m}/{base_n})")

    results = []
    try:
        for idx, val in enumerate(vals, 1):
            token = fmt(val, args.is_float)
            t0 = time.time()

            with open(SRC, "w", encoding="utf-8") as f:
                f.write(orig_text)
            new_text, _ = set_define_value(orig_text, args.define, token)
            with open(SRC, "w", encoding="utf-8") as f:
                f.write(new_text)

            ok, out = run_step(f'"{JNI_BUILD}"')
            if not ok or "successful" not in out:
                print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  DLL 编译失败，跳过")
                results.append((token, None, None, None, time.time() - t0))
                continue

            ok, out = run_step(f'"{RUN_BAT}"')
            if not ok or "Done" not in out:
                print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  simulator 运行失败，跳过")
                results.append((token, None, None, None, time.time() - t0))
                continue

            for _attempt in range(6):
                try:
                    if os.path.exists(report_file):
                        os.remove(report_file)
                    break
                except PermissionError:
                    time.sleep(0.5)

            ok, out = run_step(f'"{sys.executable}" "{report_script}"{stage_args}', cwd=HERE)
            if not ok:
                print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  报告生成失败，跳过")
                results.append((token, None, None, None, time.time() - t0))
                continue

            r = read_accuracy(report_file)
            elapsed = time.time() - t0
            if r is None:
                print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  未解析到准确率 ({elapsed:.1f}s)")
                results.append((token, None, None, None, elapsed))
                continue

            acc, mm, nn = r
            results.append((token, acc, mm, nn, elapsed))
            mark = ""
            if args.is_float:
                try:
                    if abs(float(token) - float(start_token)) < 1e-9:
                        mark = "   <- 起点值"
                except ValueError:
                    pass
            elif token == str(start_token):
                mark = "   <- 起点值"
            print(f"[{idx:2d}/{len(vals)}] {args.define}={token:>6}  Accuracy={acc:6.2f}% ({mm}/{nn})  {elapsed:4.1f}s{mark}")
    finally:
        with open(SRC, "w", encoding="utf-8") as f:
            f.write(true_orig)
        ok, out = run_step(f'"{JNI_BUILD}"')
        if ok and "successful" in out:
            print("-" * 72)
            print("[sweep] 源码已恢复并按原始值重编译 DLL")
        else:
            print("[sweep][WARN] 恢复后重编译失败，请手动运行 jni\\build.bat")

    valid = [r for r in results if r[1] is not None]
    if not valid:
        print("[sweep] 没有可用结果")
        return 1

    csv_path = os.path.join(HERE, f"sweep_{args.define}_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["value", "overall_accuracy_pct", "matches", "positions", "elapsed_s"])
        for token, acc, mm, nn, el in results:
            w.writerow([token, "" if acc is None else f"{acc:.2f}",
                        "" if mm is None else mm, "" if nn is None else nn, f"{el:.1f}"])
    print(f"[sweep] 扫描表已保存: {csv_path}")

    best_acc = max(r[1] for r in valid)
    best_all = [r for r in valid if r[1] == best_acc]
    def dist_orig(r):
        try:
            return abs(float(r[0]) - float(start_token))
        except ValueError:
            return 1e18
    best_all.sort(key=dist_orig)
    best = best_all[0]

    print("=" * 72)
    print(f"[sweep] 最优 {args.define} = {best[0]}  ->  Overall Accuracy = {best[1]:.2f}% ({best[2]}/{best[3]})")
    if len(best_all) > 1:
        print(f"[sweep] 共 {len(best_all)} 个等效最优值: {[r[0] for r in best_all]}")
    try:
        base = [r for r in valid if abs(float(r[0]) - float(start_token)) < 1e-9]
        if base and base[0][1] is not None:
            print(f"[sweep] 起点值 {start_token} 的 Accuracy = {base[0][1]:.2f}% ({base[0][2]}/{base[0][3]})，"
                  f"提升 {best[1] - base[0][1]:+.2f} 个百分点")
    except ValueError:
        pass

    best_str = compress_values([r[0] for r in best_all])
    new_line = f"{args.define}={best_str}"
    for fname in os.listdir(input_dir):
        if not fname.endswith(".txt"):
            continue
        def_path = os.path.join(output_dir, fname.replace(".txt", f".{TARGET}.def"))
        lines = {}
        if os.path.exists(def_path):
            with open(def_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k = line.split("=", 1)[0]
                        lines[k] = line
        lines[args.define] = new_line
        with open(def_path, "w", encoding="utf-8") as f:
            for v in lines.values():
                f.write(v + "\n")
    print(f"[sweep] 最优参数已写入: {output_dir}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="扫描 #define 宏取值，最大化 Accuracy")
    ap.add_argument("--define", default="MIDDLE_THRESHOLD", help="宏名（默认 MIDDLE_THRESHOLD）")
    ap.add_argument("--start", type=float, help="扫描起始值（含）")
    ap.add_argument("--stop", type=float, help="扫描结束值（含）")
    ap.add_argument("--step", type=float, default=1.0, help="步长（默认 1）")
    ap.add_argument("--values", type=str, help="显式候选值，逗号分隔，如 3,5,7")
    ap.add_argument("--float", dest="is_float", action="store_true", help="宏为浮点值")
    ap.add_argument("--subdir", default="N1", help="子目录（默认 N1）")
    ap.add_argument("--per-file", action="store_true",
                    help="逐文件模式：为每个文件找各自的最优值")
    ap.add_argument("--stage1", action="store_true")
    ap.add_argument("--stage2", action="store_true")
    ap.add_argument("--stage3", action="store_true")
    args = ap.parse_args()

    if args.values:
        vals = [float(v) for v in args.values.split(",") if v.strip()]
    else:
        if args.start is None or args.stop is None:
            raise SystemExit("[ERROR] 需要 --start/--stop/--step 或 --values")
        vals = []
        v = args.start
        if args.step > 0:
            while v <= args.stop + 1e-9:
                vals.append(round(v, 9))
                v += args.step
        else:
            while v >= args.stop - 1e-9:
                vals.append(round(v, 9))
                v += args.step
    if not vals:
        raise SystemExit("[ERROR] 候选值为空")

    if args.per_file:
        return sweep_per_file(args, vals)
    else:
        return sweep_overall(args, vals)


if __name__ == "__main__":
    sys.exit(main())
