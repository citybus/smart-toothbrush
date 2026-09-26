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
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_FILE = os.path.join(HERE, "sweep_define.def")
SWEEP_PY = os.path.join(HERE, "sweep_define.py")
REPORT_DIR = os.path.join(HERE, '..', 'report')

TARGET = "overall"  # 可选: "per-file" | "overall"
# per-file: 逐文件模式，为每个文件找各自的最优值
# overall: 整体模式，扫描所有文件，找 overall 最优值


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

    print(f"[run_sweep] 读取 {len(entries)} 个宏定义:")
    for macro, extra in entries:
        print(f"  {macro} {' '.join(extra)}")
    print("=" * 72)

    for macro, extra_args in entries:
        print(f"\n[run_sweep] 扫描 {macro}")

        cmd = [
            sys.executable, SWEEP_PY,
            "--define", macro,
        ]
        if TARGET == "per-file":
            cmd.append("--per-file")
        for name in stage_flags:
            cmd.append(f"--{name}")
        cmd.extend(extra_args)

        p = subprocess.run(cmd, cwd=HERE)
        if p.returncode != 0:
            print(f"[run_sweep] {macro} 扫描失败 (exit={p.returncode})")

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
