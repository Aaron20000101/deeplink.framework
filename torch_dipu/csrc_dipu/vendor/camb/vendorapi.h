#pragma once

#include <cnrt.h>
#include <cndev.h>
#include <cnnl.h>

#include <csrc_dipu/common.h>

namespace dipu {

#define DIPU_CALLCNRT(Expr)                                                 \
    {                                                                          \
        ::cnrtRet_t ret = Expr;                                                \
        if (ret != ::CNRT_RET_SUCCESS) {                                       \
            throw std::runtime_error("dipu device error");          \
        }                                                                      \
    }

#define DIPU_CALLCNDEV(Expr)                                                \
    {                                                                          \
        ::cndevRet_t ret = Expr;                                               \
        if (ret != ::CNDEV_SUCCESS) {                                          \
            throw std::runtime_error("dipu device error");          \
        }                                                                      \
    }
  
#define DIPU_CALLCNNL(Expr)                                                 \
    {                                                                          \
        ::cnnlStatus_t ret = Expr;                                             \
        if (ret != ::CNNL_STATUS_SUCCESS) {                                    \
            throw std::runtime_error("dipu device error");          \
        }                                                                      \
    }


#define DIPU_INIT_CNDEV_VERSION(info) info.version = CNDEV_VERSION_5;
using deviceStream_t = cnrtQueue_t;
#define deviceDefaultStreamLiteral nullptr
using deviceEvent_t = cnrtNotifier_t;
using deviceHandle_t = cnnlHandle_t;

}
