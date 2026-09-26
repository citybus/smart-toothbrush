/**
 * Smart Toothbrush Algorithm Simulator
 * 
 * Reads IMU data files from input/, calls the DLL algorithm,
 * and writes output files with V1-V16 results to output/.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <math.h>

/* ---- DLL Function prototypes ---- */
typedef void     (*fn_init)(void);
typedef unsigned short (*fn_update)(float *accVal, float *gyroVal, short pressState,
                                    float *forceVal, short *area, short *area2,
                                    short *area3, short *para);
typedef void    (*fn_update_timestamp)(int time);

/* ---- Global variables exported by DLL ---- */
float *g_V1, *g_V2, *g_V3, *g_V4, *g_V5, *g_V6, *g_V7, *g_V8;
float *g_V9, *g_V10, *g_V11, *g_V12, *g_V13, *g_V14, *g_V15, *g_V16;

/* Helper: get pointer to exported DATA variable from DLL */
static int get_var(HMODULE dll, const char *name, void **out) {
    FARPROC addr = GetProcAddress(dll, name);
    if (!addr) {
        fprintf(stderr, "  [WARN] cannot find variable: %s\n", name);
        *out = NULL;
        return -1;
    }
    *out = (void *)addr;
    return 0;
}

/* Helper: get pointer to exported function from DLL */
static int get_fn(HMODULE dll, const char *name, FARPROC *out) {
    *out = GetProcAddress(dll, name);
    if (!out) {
        fprintf(stderr, "  [ERROR] cannot find function: %s\n", name);
        return -1;
    }
    return 0;
}

/* Process a single input file */
static int process_file(HMODULE dll, fn_update alg_update,
                        fn_update_timestamp update_ts,
                        const char *in_path, const char *out_path) {
    FILE *fin = fopen(in_path, "r");
    if (!fin) {
        fprintf(stderr, "  [ERROR] cannot open input: %s\n", in_path);
        return -1;
    }
    FILE *fout = fopen(out_path, "w");
    if (!fout) {
        fprintf(stderr, "  [ERROR] cannot open output: %s\n", out_path);
        fclose(fin);
        return -1;
    }

    char line[4096];

    /* Check file is not empty */
    if (!fgets(line, sizeof(line), fin)) {
        fprintf(stderr, "  [ERROR] empty input file: %s\n", in_path);
        fclose(fin);
        fclose(fout);
        return -1;
    }

    /* First line is data (no header in input), process it immediately */

    /* Allocate output arrays */
    short area[18]  = {0};
    short area2[18] = {0};
    short area3[18] = {0};
    short para[16]  = {0};

    int line_num = 0;
    int prev_timestamp = -1;  /* -1 means no previous data yet */
    int prev_v9 = 0;          /* 上一行 V9 值,用于检测 0->1 上升沿 */
    int v9_rise_count = 0;    /* 本文件 V9 由 0 变 1 的累计次数(写入输出第 30 列) */

    /* Process first line (already read above), then continue reading */
    do {
        int ver, datatype, devtype, R1;
        int accx, accy, accz;
        int gyrox, gyroy, gyroz;
        int forcex, forcey, forcez;
        int v1, v2, v3, v4, v5, v6, v7, v8, v9, v10, v11, v12, v13, v14, v15, v16;
        int R2, R3, R4, R5, R6, R7;
        int timestamp;

        /* Parse all 35 columns from input */
        int n = sscanf(line,
            "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
            &ver, &datatype, &devtype, &R1,
            &accx, &accy, &accz,
            &gyrox, &gyroy, &gyroz,
            &forcex, &forcey, &forcez,
            &v1, &v2, &v3, &v4, &v5, &v6, &v7, &v8,
            &v9, &v10, &v11, &v12, &v13, &v14, &v15, &v16,
            &R2, &R3, &R4, &R5, &R6, &R7, &timestamp);

        if (n < 35) {
            /* skip malformed lines, but also skip if it's just a trailing empty line */
            if (line[0] == '\n' || line[0] == '\r' || line[0] == '\0')
                continue;
            /* try to handle last line without proper termination */
        }

        float accVal[3], gyroVal[3], forceVal[3];
        const float senAcc  = 0.00048828125f;
        const float senGyro = 0.06103515625f;
        accVal[0]  = (float)accx * senAcc;
        accVal[1]  = (float)accy * senAcc;
        accVal[2]  =  (float)accz * senAcc;
        gyroVal[0] = (float)gyrox * senGyro;
        gyroVal[1] = (float)gyroy * senGyro;
        gyroVal[2] =  (float)gyroz * senGyro;
        forceVal[0] = (float)forcex;
        forceVal[1] = (float)forcey;
        forceVal[2] = (float)forcez;

        /* Update timestamp before calling algorithm
         * time = current timestamp - previous timestamp
         * First call uses default value of 10
         */
        int time_diff;
        if (prev_timestamp < 0) {
            time_diff = 10;  /* default for first sample */
        } else {
            time_diff = timestamp - prev_timestamp;
        }
        prev_timestamp = timestamp;
        update_ts(time_diff);

        /* Call DLL algorithm
         * First 4 lines: pressState=0 (initialization phase, motor off, brush horizontal)
         * After 4 lines: pressState=3 (running phase, motor on)
         */
        short pressState = (devtype == 0) ? 0 : 3;
        alg_update(accVal, gyroVal, pressState, forceVal, area, area2, area3, para);

        /* V9 (第 22 列) 0->1 上升沿检测:每次 V9 变 1,计数加 1 */
        int cur_v9 = (int)(*g_V9 * 1);
        if (cur_v9 == 1 && prev_v9 == 0)
            v9_rise_count++;
        prev_v9 = cur_v9;

        /* Write output line: same structure as input, V1-V16 from DLL, column 30 = V9 变1累计次数 */
        fprintf(fout,
            "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
            ver, datatype, devtype, R1,
            accx, accy, accz,
            gyrox, gyroy, gyroz,
            forcex, forcey, forcez,
            (int)(*g_V1  * 1), (int)(*g_V2  * 1), (int)(*g_V3  * 1),
            (int)(*g_V4  * 1), (int)(*g_V5  * 1), (int)(*g_V6  * 1),
            (int)(*g_V7  * 1), (int)(*g_V8  * 1), (int)(*g_V9  * 1),
            (int)(*g_V10 * 1), (int)(*g_V11 * 1), (int)(*g_V12 * 1),
            (int)(*g_V13 * 1), (int)(*g_V14 * 1), (int)(*g_V15 * 1),
            (int)(*g_V16 * 1),
            v9_rise_count,
            R3,
            R4, R5, R6, R7,
            timestamp);

        line_num++;
    } while (fgets(line, sizeof(line), fin));

    printf("  Processed %d lines -> %s\n", line_num, out_path);

    fclose(fin);
    fclose(fout);
    return 0;
}

/* ---- DLL load/unload helpers ---- */
static int load_dll(const char *dll_path, HMODULE *dll_out,
                    fn_init *init_out, fn_update *update_out, fn_update_timestamp *ts_out) {
    HMODULE dll = LoadLibrary(dll_path);
    if (!dll) {
        fprintf(stderr, "[ERROR] LoadLibrary failed: %s (err=%lu)\n", dll_path, GetLastError());
        return -1;
    }
    fn_init   fi; fn_update fu; fn_update_timestamp ft;
    if (get_fn(dll, "init",   (FARPROC *)&fi) != 0) { FreeLibrary(dll); return -1; }
    if (get_fn(dll, "alg_toothbrush_update", (FARPROC *)&fu) != 0) { FreeLibrary(dll); return -1; }
    if (get_fn(dll, "update_deltatime",      (FARPROC *)&ft) != 0) { FreeLibrary(dll); return -1; }
    get_var(dll, "V1",  (void **)&g_V1);  get_var(dll, "V2",  (void **)&g_V2);
    get_var(dll, "V3",  (void **)&g_V3);  get_var(dll, "V4",  (void **)&g_V4);
    get_var(dll, "V5",  (void **)&g_V5);  get_var(dll, "V6",  (void **)&g_V6);
    get_var(dll, "V7",  (void **)&g_V7);  get_var(dll, "V8",  (void **)&g_V8);
    get_var(dll, "V9",  (void **)&g_V9);  get_var(dll, "V10", (void **)&g_V10);
    get_var(dll, "V11", (void **)&g_V11); get_var(dll, "V12", (void **)&g_V12);
    get_var(dll, "V13", (void **)&g_V13); get_var(dll, "V14", (void **)&g_V14);
    get_var(dll, "V15", (void **)&g_V15); get_var(dll, "V16", (void **)&g_V16);
    *dll_out = dll; *init_out = fi; *update_out = fu; *ts_out = ft;
    return 0;
}

static void unload_dll(HMODULE dll) {
    if (dll) FreeLibrary(dll);
}

/* Create directory if it doesn't exist */
static void ensure_dir(const char *path) {
    CreateDirectory(path, NULL);
}

/* Recursively process all files in input directory and subdirectories */
static int list_and_process_recursive(const char *dll_path,
                                       const char *input_dir, const char *output_dir) {
    char search_path[MAX_PATH];
    snprintf(search_path, sizeof(search_path), "%s\\*", input_dir);

    WIN32_FIND_DATA fdata;
    HANDLE hFind = FindFirstFile(search_path, &fdata);
    if (hFind == INVALID_HANDLE_VALUE) {
        return 0;
    }

    int count = 0;
    do {
        /* Skip . and .. */
        if (strcmp(fdata.cFileName, ".") == 0 || strcmp(fdata.cFileName, "..") == 0)
            continue;

        char in_path[MAX_PATH], out_path[MAX_PATH];
        snprintf(in_path,  sizeof(in_path),  "%s\\%s", input_dir,  fdata.cFileName);
        snprintf(out_path, sizeof(out_path), "%s\\%s", output_dir, fdata.cFileName);

        if (fdata.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            /* Subdirectory: create output dir and recurse */
            ensure_dir(out_path);
            count += list_and_process_recursive(dll_path, in_path, out_path);
        } else {
            /* File: only process .txt files */
            const char *dot = strrchr(fdata.cFileName, '.');
            if (!dot || _stricmp(dot, ".txt") != 0)
                continue;
            /* Load fresh DLL for each file */
            HMODULE dll; fn_init fi; fn_update fu; fn_update_timestamp ft;
            if (load_dll(dll_path, &dll, &fi, &fu, &ft) != 0) {
                fprintf(stderr, "[SKIP] cannot load DLL for %s\n", fdata.cFileName);
                continue;
            }
            fi();
            printf("[Processing] %s\n", in_path);
            process_file(dll, fu, ft, in_path, out_path);
            unload_dll(dll);
            count++;
        }
    } while (FindNextFile(hFind, &fdata));

    FindClose(hFind);
    return count;
}

/* Process all files in input directory and subdirectories */
static int list_and_process(const char *dll_path,
                             const char *input_dir, const char *output_dir) {
    ensure_dir(output_dir);
    return list_and_process_recursive(dll_path, input_dir, output_dir);
}

int main(int argc, char *argv[]) {
    char dll_path[MAX_PATH];
#ifdef CUSTOM_DLL
    strncpy(dll_path, CUSTOM_DLL, sizeof(dll_path) - 1);
#else
    /* 从 EXE 路径推导 DLL 路径:
     * 模式1 (旧): simulator.exe -> ..\dll\alg_toothbrushpc.dll
     * 模式2 (新): all\<subdir>\xxx.exe -> ROOT\dll\all\<subdir>\xxx.dll
     */
    GetModuleFileName(NULL, dll_path, sizeof(dll_path));
    /* 判断是否在 simulator\all\<subdir>\ 下 */
    char *test_p = strrchr(dll_path, '\\');
    int in_subdir = 0;
    if (test_p) {
        *test_p = '\0';
        char *parent = strrchr(dll_path, '\\');
        if (parent) {
            *parent = '\0';
            char *grandparent = strrchr(dll_path, '\\');
            if (grandparent) {
                /* 检查是否 ...\simulator\all\<subdir> */
                if (_stricmp(grandparent + 1, "all") == 0)
                    in_subdir = 1;
            }
        }
        /* 恢复 dll_path */
        GetModuleFileName(NULL, dll_path, sizeof(dll_path));
    }

    if (in_subdir) {
        /* 新模式: all\<subdir>\xxx.exe -> ROOT\dll\all\<subdir>\xxx.dll */
        char *p = strrchr(dll_path, '\\');
        if (p) *p = '\0';  /* 去掉 xxx.exe */
        p = strrchr(dll_path, '\\');
        if (p) *p = '\0';  /* 去掉 subdir */
        char subdir[MAX_PATH];
        strncpy(subdir, p ? p + 1 : "", sizeof(subdir) - 1);
        subdir[sizeof(subdir) - 1] = '\0';
        p = strrchr(dll_path, '\\');
        if (p) *p = '\0';  /* 去掉 all */
        p = strrchr(dll_path, '\\');
        if (p) *p = '\0';  /* 去掉 simulator，得到 ROOT */
        char root_dir[MAX_PATH];
        strncpy(root_dir, dll_path, sizeof(root_dir) - 1);
        root_dir[sizeof(root_dir) - 1] = '\0';
        char exe_name[MAX_PATH];
        const char *ename = strrchr(argv[0], '\\');
        ename = ename ? ename + 1 : argv[0];
        strncpy(exe_name, ename, sizeof(exe_name) - 1);
        exe_name[sizeof(exe_name) - 1] = '\0';
        char *dot = strrchr(exe_name, '.');
        if (dot) *dot = '\0';
        snprintf(dll_path, sizeof(dll_path), "%s\\dll\\all\\%s\\%s.dll",
                 root_dir, subdir, exe_name);
    } else {
        /* 旧模式: simulator.exe -> ..\dll\alg_toothbrushpc.dll */
        strcpy(dll_path, "..\\dll\\alg_toothbrushpc.dll");
    }
#endif
    const char *input_dir   = (argc > 1) ? argv[1] : "..\\input";
    const char *output_dir  = (argc > 2) ? argv[2] : "..\\output";
    const char *single_file = (argc > 3) ? argv[3] : NULL;

    printf("=== Smart Toothbrush Algorithm Simulator ===\n\n");
    printf("[1] DLL: %s\n\n", dll_path);

    /* Process input files - each file loads its own fresh DLL */
    printf("[Processing]\n");
    int n = 0;
    if (single_file) {
        /* Single file mode */
        char out_file[MAX_PATH];
        const char *base = strrchr(single_file, '\\');
        if (!base) base = strrchr(single_file, '/');
        if (base) base++; else base = single_file;
        snprintf(out_file, sizeof(out_file), "%s\\%s", output_dir, base);
        HMODULE dll; fn_init fi; fn_update fu; fn_update_timestamp ft;
        if (load_dll(dll_path, &dll, &fi, &fu, &ft) != 0) {
            fprintf(stderr, "[ERROR] cannot load DLL\n");
            return 1;
        }
        fi();
        printf("[Processing] %s -> %s\n", single_file, out_file);
        process_file(dll, fu, ft, single_file, out_file);
        unload_dll(dll);
        n = 1;
    } else {
        n = list_and_process(dll_path, input_dir, output_dir);
    }

    printf("\n=== Done. Processed %d file(s). ===\n", n);
    return 0;
}
