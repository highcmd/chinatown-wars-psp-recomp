#pragma once
#include <cstdio>
#define INFO_LOG(cat, ...) ((void)0)
#define DEBUG_LOG(cat, ...) ((void)0)
#define WARN_LOG(cat, ...) (fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
#define ERROR_LOG(cat, ...) (fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
