"""
run_sweep_all.py - 读取 sweep_define.def，对每个宏调用 sweep_define.py 扫描最佳参数。
流程：
  对每个宏：
    1) 更新 .def 文件中的宏值
    2) 编译 per-file DLL/EXE
    3) 跑仿真、生成报告
    4) 根据报告更新 .def 文件
  每个宏扫完后，.def 文件保留最优值，下一个宏从这个基线继续扫
参数：
  --stage1 start end  只扫描 sweep_define.def 中第 start 行到第 end 行的宏
  --stage2 start end  同上
  --stage3 start end  同上
  不带参数时扫描全部
"""
import argparse
import os
import re
import shutil
import sys
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_FILE = os.path.join(HERE, "sweep_define.def")
SWEEP_PY = os.path.join(HERE, "sweep_define.py")
REPORT_DIR = os.path.join(HERE, '..', 'report')
INPUT_ROOT = os.path.join(HERE, '..', 'input')
JNI_BUILD = os.path.join(HERE, '..', 'jni', 'build.bat')
JNI_BUILD_ALL = os.path.join(HERE, '..', 'jni', 'build_all.bat')
SIM_BUILD = os.path.join(HERE, 'build.bat')
SIM_BUILD_ALL = os.path.join(HERE, 'build_all.bat')

TARGET = "overall"  # 可选: "per-file" | "overall"
# per-file: 逐文件模式，为每个文件找各自的最优值
# overall: 整体模式，扫描所有文件，找 overall 最优值
LOOP = 3
LOO = "disable"  # 宏定义: disable=原有功能; enable=LOO（按文件留一）验证
OUTPUT_ROOT = os.path.join(HERE, '..', 'output')
DEF_SUFFIX = ".time.def"  # 与 sweep_define.py TARGET="time" 一致
LOO_SUBDIR = "LOO"  # LOO 折后 def 统一存放的子目录名

def _natkey(s):
    """自然排序key：数字片段按数值比，禁止裸 sorted() 字符串序"""
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def _loo_verdict(seq):
    """LOO 最优值序列 -> 一致/分歧判定"""
    if not seq:
        return "无文件"
    if "?" in seq:
        return f"含失败{seq.count('?')}个"
    return "一致" if len(set(seq)) == 1 else "分歧"


def _parse_fold_accs(text, macro):
    """解析每候选准确率行: [ 3/10] TH=    15  Accuracy= 99.31% (2431/2448)
    返回 {候选值: 准确率%}"""
    pat = r"\]\s*" + re.escape(macro) + r"=\s*(\S+)\s+Accuracy=\s*([0-9.]+)"
    return {v: float(a) for v, a in re.findall(pat, text)}


def _loo_base_and_diffs(seq, accs):
    """基准 = 出现次数最多的最优值（并列取先出现的）；
    每折差 = 该折最优准确率 - 基准值在该折的准确率（百分点），缺数据记 ?"""
    counts, first = {}, {}
    for i, v in enumerate(seq):
        if v == "?":
            continue
        counts[v] = counts.get(v, 0) + 1
        first.setdefault(v, i)
    if not counts:
        return None, 0, []
    base = min(counts, key=lambda v: (-counts[v], first[v]))
    diffs = []
    for i, v in enumerate(seq):
        ca = accs[i] if i < len(accs) else {}
        fa, ba = ca.get(v), ca.get(base)
        diffs.append("?" if fa is None or ba is None else f"{fa - ba:+.2f}")
    return base, counts[base], diffs


def _read_def(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip()]


def _write_def(path, lines):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for l in lines:
            f.write(l + "\n")


def _main_def_path(out_dir, fn):
    return os.path.join(out_dir, fn[:-len(".txt")] + DEF_SUFFIX)


def _set_def_value(lines, macro, value):
    """返回 lines 的拷贝，macro 行改为 macro=value（没有则追加）"""
    out, found = [], False
    for l in lines:
        if "=" in l and l.split("=", 1)[0].strip() == macro:
            out.append(f"{macro}={value}")
            found = True
        else:
            out.append(l)
    if not found:
        out.append(f"{macro}={value}")
    return out


def _stored_def_path(out_dir, fn):
    """LOO 子目录里的折后 def：output/<subdir>/LOO/<文件名>.time.def"""
    stem = fn[:-len(".txt")]
    return os.path.join(out_dir, LOO_SUBDIR, stem + DEF_SUFFIX)


def run_loo_folds(subdir, cmd, macro):
    """LOO 模式：每次留出 1 个文件（input+output 同时移出），跑一次扫描。
    该折最优只合并写入该文件的子目录 def，主目录不动；
    主目录回写由 loo_write_back 在全部宏扫完后执行。"""
    in_dir = os.path.abspath(os.path.join(INPUT_ROOT, subdir))
    out_dir = os.path.abspath(os.path.join(OUTPUT_ROOT, subdir))
    files = sorted((f for f in os.listdir(in_dir) if f.endswith(".txt")),
                   key=_natkey)
    hold_root = os.path.join(tempfile.gettempdir(), "sweep_loo_hold")

    # 恢复上次异常中断遗留在暂存目录的文件
    for tag, d in (("in", in_dir), ("out", out_dir)):
        hold_dir = os.path.join(hold_root, tag, subdir)
        if os.path.isdir(hold_dir):
            for f in os.listdir(hold_dir):
                dst = os.path.join(d, f)
                if not os.path.exists(dst):
                    shutil.move(os.path.join(hold_dir, f), dst)

    bests = []
    fold_accs = []  # 每折 {候选值: 准确率%}
    for k, fn in enumerate(files, 1):
        held = []
        for tag, d in (("in", in_dir), ("out", out_dir)):
            src = os.path.join(d, fn)
            if os.path.exists(src):
                dst_dir = os.path.join(hold_root, tag, subdir)
                os.makedirs(dst_dir, exist_ok=True)
                dst = os.path.join(dst_dir, fn)
                shutil.move(src, dst)
                held.append((src, dst))
        print(f"[LOO] 留出 {subdir}/{fn}（{k}/{len(files)}）")
        best = "?"
        text = []
        try:
            p = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
            for line in p.stdout or "":
                sys.stdout.write(line)
                text.append(line)
            ms = re.findall(r"\[sweep\] 最优 (\S+) = (\S+)", "".join(text))
            if p.returncode == 0 and ms:
                best = ms[-1][1]
        finally:
            for src, dst in held:
                shutil.move(dst, src)
        bests.append(best)
        fold_accs.append(_parse_fold_accs("".join(text), macro))
        # 该折最优合并进该文件子目录 def（没有存档就以它自己的主 def 为底）
        if best != "?":
            stored = _stored_def_path(out_dir, fn)
            base = _read_def(stored)
            if not base:
                base = _read_def(_main_def_path(out_dir, fn))
            _write_def(stored, _set_def_value(base, macro, best))
    return bests, fold_accs


def loo_write_back(subdir):
    """全部宏扫完：把 LOO 子目录里各文件的 def 放进主目录；没有 def 的文件不动"""
    out_dir = os.path.abspath(os.path.join(OUTPUT_ROOT, subdir))
    loo_dir = os.path.join(out_dir, LOO_SUBDIR)
    if not os.path.isdir(loo_dir):
        return 0
    n = 0
    for name in sorted(os.listdir(loo_dir), key=_natkey):
        stored = os.path.join(loo_dir, name)
        if os.path.isfile(stored) and name.endswith(DEF_SUFFIX):
            _write_def(os.path.join(out_dir, name), _read_def(stored))
            n += 1
    return n


def parse_def_file(def_path):
    entries = []
    with open(def_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not parts:
                continue
            macro = parts[0]
            if "--start" in parts:
                entries.append((macro, parts[1:]))
            elif "=" in line:
                k, v = line.split("=", 1)
                entries.append((k.strip(), ["--values", v.strip()]))
    return entries


def parse_def_file_by_lines(def_path):
    """按行号解析，保留空行和注释行的位置信息，返回 (行号, macro, args) 列表"""
    entries = []
    with open(def_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not parts:
                continue
            macro = parts[0]
            if "--start" in parts:
                entries.append((lineno, macro, parts[1:]))
            elif "=" in line:
                k, v = line.split("=", 1)
                entries.append((lineno, k.strip(), ["--values", v.strip()]))
    return entries


def main():
    parser = argparse.ArgumentParser(description="批量扫描 sweep_define.def 中的宏")
    parser.add_argument("--stage1", nargs=2, type=int, metavar=("START", "END"),
                        help="扫描 sweep_define.def 中第 START 行到第 END 行的宏")
    parser.add_argument("--stage2", nargs=2, type=int, metavar=("START", "END"),
                        help="扫描 sweep_define.def 中第 START 行到第 END 行的宏")
    parser.add_argument("--stage3", nargs=2, type=int, metavar=("START", "END"),
                        help="扫描 sweep_define.def 中第 START 行到第 END 行的宏")
    args = parser.parse_args()

    if not os.path.exists(DEF_FILE):
        print(f"[ERROR] 找不到 {DEF_FILE}")
        return 1

    all_entries = parse_def_file_by_lines(DEF_FILE)
    if not all_entries:
        print(f"[ERROR] {DEF_FILE} 为空或格式错误")
        return 1

    # 收集指定行号范围内的宏
    stage_ranges = []
    stage_flags = {}
    for name in ("stage1", "stage2", "stage3"):
        val = getattr(args, name)
        if val is not None:
            stage_ranges.append((name, val[0], val[1]))
            stage_flags[name] = True

    if stage_ranges:
        entries = []
        for stage_name, start, end in stage_ranges:
            for lineno, macro, extra in all_entries:
                if start <= lineno <= end:
                    entries.append((macro, extra))
            print(f"[run_sweep] {stage_name}: 第 {start}-{end} 行")
    else:
        entries = [(macro, extra) for _, macro, extra in all_entries]

    if not entries:
        print(f"[ERROR] 指定行号范围内没有找到宏定义")
        return 1

    # 输入子目录从 input/ 目录发现，不硬编码（如 N1），传给 sweep_define.py --subdir
    if not os.path.isdir(INPUT_ROOT):
        print(f"[ERROR] 找不到输入目录 {INPUT_ROOT}")
        return 1
    subdirs = sorted(
        (d for d in os.listdir(INPUT_ROOT)
         if os.path.isdir(os.path.join(INPUT_ROOT, d))),
        key=_natkey)
    if not subdirs:
        print(f"[ERROR] {INPUT_ROOT} 下没有子目录")
        return 1
    print(f"[run_sweep] 输入子目录: {', '.join(subdirs)}")

    print(f"[run_sweep] 读取 {len(entries)} 个宏定义:")
    for macro, extra in entries:
        print(f"  {macro} {' '.join(extra)}")
    print("=" * 72)

    # 全程只在最开始编译一次（把 setpara 新代码编进 EXE/DLL），扫描中不再重编
    if TARGET == "per-file":
        first_builds = [("DLL", JNI_BUILD_ALL), ("EXE", SIM_BUILD_ALL)]
    else:
        first_builds = [("EXE", SIM_BUILD), ("DLL", JNI_BUILD)]
    print("[run_sweep] 初始编译（全程仅此一次，扫描中不再重编）")
    for what, bat in first_builds:
        p = subprocess.run(f'"{bat}"', shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        bout = p.stdout or ""
        ok = p.returncode == 0 and "Build FAILED" not in bout
        if bat == JNI_BUILD and "successful" not in bout:
            ok = False
        if not ok:
            print(f"[run_sweep][ERROR] 初始 {what} 编译失败: {bat}")
            for l in bout.strip().splitlines()[-5:]:
                print("    " + l)
            return 1

    loo_summary = []  # [(subdir, macro, bests)] 最终汇总用
    # LOOP=整套流程重复轮数：每轮从上一轮 def 最优值继续扫
    n_passes = LOOP if LOOP >= 1 else 1
    for loop_idx in range(1, n_passes + 1):
        if n_passes > 1:
            print(f"\n[run_sweep] ==== 第 {loop_idx}/{n_passes} 轮扫描 ====")
        for subdir in subdirs:
            print(f"\n[run_sweep] 子目录 {subdir} 开始")
            for macro, extra_args in entries:
                print(f"\n[run_sweep] 扫描 {macro}")

                cmd = [
                    sys.executable, SWEEP_PY,
                    "--define", macro,
                    "--subdir", subdir,
                ]
                if TARGET == "per-file":
                    cmd.append("--per-file")
                for name in stage_flags:
                    cmd.append(f"--{name}")
                cmd.extend(extra_args)

                if LOO == "enable":
                    fold_best, fold_accs = run_loo_folds(subdir, cmd, macro)
                    print(f"[LOO] {macro} 最优值序列: "
                          + " -> ".join(fold_best)
                          + f" ({_loo_verdict(fold_best)})")
                    loo_summary.append((subdir, macro, fold_best, fold_accs))
                else:
                    p = subprocess.run(cmd, cwd=HERE)
                    if p.returncode != 0:
                        print(f"[run_sweep] {macro} 扫描失败 (exit={p.returncode})")

            # 全部宏扫完，子目录 def 放进主目录（没有的文件不动）
            if LOO == "enable":
                n = loo_write_back(subdir)
                print(f"[LOO] {subdir}: {n} 个文件的子目录 def 已放入主目录")

            # 扫描结束：用最优参数最后跑一遍并重新生成报告
            cmd_final = [sys.executable, SWEEP_PY, "--subdir", subdir, "--final"]
            if TARGET == "per-file":
                cmd_final.append("--per-file")
            for name in stage_flags:
                cmd_final.append(f"--{name}")
            p = subprocess.run(cmd_final, cwd=HERE)
            if p.returncode != 0:
                print(f"[run_sweep] {subdir} 最终报告生成失败 (exit={p.returncode})")

    print("\n" + "=" * 72)
    print("[run_sweep] 全部完成")

    # 对所有备份文件写入分隔符，标记左侧积累结束，下次写入进入右侧模式
    if os.path.isdir(REPORT_DIR):
        separator = "=" * 50 + "\n"
        for subdir_name in os.listdir(REPORT_DIR):
            subdir_path = os.path.join(REPORT_DIR, subdir_name)
            if not os.path.isdir(subdir_path):
                continue
            for fname in os.listdir(subdir_path):
                if not fname.endswith('.txt') or fname.startswith('report_'):
                    continue
                fpath = os.path.join(subdir_path, fname)
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(separator)
        print("[run_sweep] 已写入备份文件分隔符")

    # 终端最终汇总：全部参数最优值序列再打印一遍（含一致/分歧判定）
    # 并以出现次数最多的值为基准，打印每折准确率差
    if LOO == "enable" and loo_summary:
        print("=" * 72)
        print("[LOO] 最终汇总（全部参数最优值序列）:")
        for sd, m, seq, accs in loo_summary:
            print(f"[LOO] {sd}/{m} 最优值序列: "
                  + " -> ".join(seq) + f" ({_loo_verdict(seq)})")
            base, cnt, diffs = _loo_base_and_diffs(seq, accs)
            if base is None:
                print(f"[LOO] {sd}/{m} 基准: 无可比对值")
                continue
            print(f"[LOO] {sd}/{m} 基准={base}（{cnt}/{len(seq)}）"
                  f"各折准确率差(最优-基准, 百分点): " + " ".join(diffs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
