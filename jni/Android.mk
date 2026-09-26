LOCAL_PATH := $(call my-dir)
include $(CLEAR_VARS)

LOCAL_MODULE    := alg_toothbrush
LOCAL_SRC_FILES := alg_toothbrush.c
LOCAL_CFLAGS    := -fPIC

include $(BUILD_SHARED_LIBRARY)