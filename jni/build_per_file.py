"""
build_per_file.py - 读取 input 目录的 .def 文件，为每个输入文件编译独立 DLL。

流程:
1. 扫描 input/<subdir> 目录，找所有 .def 文件
2. 每个 .def 文件对应一个输入文件
3. 读取 .def 中的宏定义，替换 alg_toothbrush.c 中的 #define
4. 编译生成 dll/all/<input_filename>.dll
5. 恢复原始源码
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(HERE, "alg_toothbrush.c")
BUILD_BAT = os.path.join(HERE, "build_all.bat")
INPUT_DIR = os.path.join(ROOT, "input")
OUTPUT_DIR = os.path.join(ROOT, "dll", "all")
DEF_DIR = os.path.join(ROOT, "output")


def get_define_value(src_text, name):
    m = re.search(
        r'^(\s*#\s*define\s+' + re.escape(name) + r'\s+)(\S+)([^\r\n]*)',
        src_text, re.MULTILINE)
    if not m:
        return None
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


def parse_def_file(def_path):
    """解析 .def 文件，返回 {macro_name: value}"""
    entries = {}
    with open(def_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                entries[k.strip()] = v.strip()
    return entries


def expand_value(val_str):
    """展开范围表示，如 '1-4:0.1' -> '1,1.1,1.2,...,4'"""
    parts = []
    for segment in val_str.split(","):
        segment = segment.strip()
        m = re.match(r'^(-?[0-9.]+)-(-?[0-9.]+):(-?[0-9.]+)$', segment)
        if m:
            start, end, step = float(m.group(1)), float(m.group(2)), float(m.group(3))
            v = start
            while v <= end + 1e-9:
                parts.append(v)
                v += step
        else:
            try:
                parts.append(float(segment))
            except ValueError:
                parts.append(segment)
    # 取第一个值作为编译参数
    if parts:
        v = parts[0]
        if isinstance(v, float) and v != int(v):
            return "%g" % v
        return str(int(v))
    return val_str


def compile_dll(src_path, out_dll):
    """调用 gcc 编译 DLL"""
    cmd = f'gcc -shared -o "{out_dll}" "{src_path}" -std=gnu11 -O2 -lm'
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.returncode == 0, p.stdout + p.stderr


def main():
    if not os.path.exists(INPUT_DIR):
        print(f"[ERROR] input 目录不存在: {INPUT_DIR}")
        return 1

    # 读取原始源码
    with open(SRC, "r", encoding="utf-8") as f:
        orig_text = f.read()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 扫描所有子目录
    subdirs = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
    if not subdirs:
        subdirs = [""]

    total = 0
    success = 0

    for subdir in subdirs:
        input_subdir = os.path.join(INPUT_DIR, subdir) if subdir else INPUT_DIR
        def_subdir = os.path.join(DEF_DIR, subdir) if subdir else DEF_DIR
        dll_subdir = os.path.join(OUTPUT_DIR, subdir) if subdir else OUTPUT_DIR
        os.makedirs(dll_subdir, exist_ok=True)

        # 找所有输入 .txt 文件
        txt_files = [f for f in os.listdir(input_subdir) if f.endswith(".txt")]

        if not txt_files:
            continue

        for txt_file in txt_files:
            base_name = txt_file[:-4]  # 去掉 .txt
            input_txt = txt_file
            dll_name = base_name + ".dll"

            # 找对应的 .def 文件（在 output 目录）
            def_file = None
            for suffix in [".face.def", ".time.def"]:
                candidate = base_name + suffix
                if os.path.exists(os.path.join(def_subdir, candidate)):
                    def_file = candidate
                    break

            if not def_file:
                # 没有 .def 文件，用原始参数编译
                dll_path = os.path.join(dll_subdir, dll_name)
                print(f"[BUILD] {dll_name} (无 .def 文件，使用原始参数)")
                ok, out = compile_dll(SRC, dll_path)
                if ok:
                    print(f"  -> 成功: {dll_path}")
                    success += 1
                else:
                    print(f"  -> 失败: {out[:200]}")
                total += 1
                continue

            def_path = os.path.join(def_subdir, def_file)
            dll_path = os.path.join(dll_subdir, dll_name)

            # 解析 .def 文件
            macros = parse_def_file(def_path)
            if not macros:
                print(f"[BUILD] {dll_name} (.def 为空，跳过)")
                continue

            # 替换源码中的宏
            new_text = orig_text
            replaced = []
            for macro_name, val_str in macros.items():
                val = expand_value(val_str)
                text, count = set_define_value(new_text, macro_name, val)
                if count > 0:
                    new_text = text
                    replaced.append(f"{macro_name}={val}")

            if not replaced:
                print(f"[BUILD] {dll_name} (无匹配宏，跳过)")
                continue

            # 写入临时源码
            with open(SRC, "w", encoding="utf-8") as f:
                f.write(new_text)

            # 编译
            print(f"[BUILD] {dll_name} <- {def_file}: {', '.join(replaced)}")
            ok, out = compile_dll(SRC, dll_path)

            # 恢复源码
            with open(SRC, "w", encoding="utf-8") as f:
                f.write(orig_text)

            if ok:
                print(f"  -> 成功: {dll_path}")
                success += 1
            else:
                print(f"  -> 失败: {out[:200]}")
            total += 1

    print(f"\n[BUILD] 完成: {success}/{total} 个 DLL 编译成功")
    print(f"[BUILD] 输出目录: {OUTPUT_DIR}")

    # 最终恢复源码
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(orig_text)

    return 0 if success > 0 else 1


if __name__ == "__main__":
    sys.exit(main())