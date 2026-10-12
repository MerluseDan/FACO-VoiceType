/* Testing-only, synthetic NVML ABI shim. Not shipped as an NVIDIA driver. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>

typedef struct {unsigned int gpu, memory;} Util;
typedef struct {uint64_t total, free, used;} Mem;
typedef struct {unsigned int pid; uint64_t usedGpuMemory;
                unsigned int gpuInstanceId, computeInstanceId;} Proc;
typedef struct {unsigned int pid; uint64_t timeStamp; unsigned int smUtil,memUtil,encUtil,decUtil;} ProcUtil;

int nvmlInit_v2(void) {return 0;}
int nvmlDeviceGetCount_v2(unsigned int *cnt){*cnt=1;return 0;}
int nvmlDeviceGetHandleByIndex_v2(unsigned int ix, void **h){if(ix) return 2;*h=(void*)(uintptr_t)0x1234;return 0;}
int nvmlDeviceGetName(void *h,char *out,unsigned int n){(void)h;const char *s="FACO Synthetic RTX Test GPU";if(n==0)return 2;strncpy(out,s,n-1);out[n-1]=0;return 0;}
int nvmlDeviceGetUtilizationRates(void*h,Util *v){(void)h;v->gpu=78;v->memory=37;return 0;}
int nvmlDeviceGetMemoryInfo(void*h,Mem *v){(void)h;v->total=16ull<<30;v->used=3ull<<30;v->free=v->total-v->used;return 0;}
int nvmlDeviceGetTemperature(void*h,unsigned int sensor,unsigned int*out){(void)h;(void)sensor;*out=53;return 0;}
int nvmlDeviceGetEncoderUtilization(void*h,unsigned int *v,unsigned int *t){(void)h;*v=24;*t=1000000;return 0;}
int nvmlDeviceGetDecoderUtilization(void*h,unsigned int *v,unsigned int *t){(void)h;*v=7;*t=1000000;return 0;}
int nvmlDeviceGetComputeRunningProcesses_v2(void*h,unsigned int *n,Proc*out){(void)h;if(!out){*n=1;return 7;}if(*n<1){*n=1;return 7;}
 *n=1;out[0].pid=getpid();out[0].usedGpuMemory=2ull<<30;out[0].gpuInstanceId=0xffffffff;out[0].computeInstanceId=0xffffffff;return 0;}
int nvmlDeviceGetGraphicsRunningProcesses_v2(void*h,unsigned int *n,Proc*out){(void)h;if(!out){*n=1;return 7;}if(*n<1){*n=1;return 7;}
 *n=1;out[0].pid=getpid();out[0].usedGpuMemory=1ull<<30;out[0].gpuInstanceId=0xffffffff;out[0].computeInstanceId=0xffffffff;return 0;}
int nvmlDeviceGetProcessUtilization(void*h,ProcUtil*out,unsigned int*n,uint64_t last){(void)h;if(last>=7100000ull)return 6;if(!out){*n=1;return 7;}if(*n<1){*n=1;return 7;}
 *n=1;out[0].pid=getpid();out[0].timeStamp=7100000ull;out[0].smUtil=69;out[0].memUtil=48;out[0].encUtil=13;out[0].decUtil=3;return 0;}
