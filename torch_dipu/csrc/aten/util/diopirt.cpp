#include "torch_dipu/csrc/aten/util/diopi.h"

#include <stdio.h>

extern "C" {

static char diopiVersion[256] = {0};

DIOPI_RT_API const char* diopiGetVersion() {
    static bool inited = false;
    if (!inited) {
        inited = true;
        snprintf(diopiVersion, sizeof(diopiVersion), "DIOPI Version: %d.%d.%d", DIOPI_VER_MAJOR, DIOPI_VER_MINOR, DIOPI_VER_PATCH);
    }
    return diopiVersion;
}

DIOPI_RT_API diopiError_t diopiGetTensorData(diopiTensorHandle_t* pth, void** pptr) {
    *pptr = (reinterpret_cast<at::Tensor*>(*pth))->data_ptr();
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorDataConst(diopiConstTensorHandle_t* pth, const void** pptr) {
    *pptr = (reinterpret_cast<const at::Tensor*>(*pth))->data_ptr();
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorShape(diopiConstTensorHandle_t pth, diopiSize_t* size) {
    const at::Tensor* ptr = reinterpret_cast<const at::Tensor*>(pth);
    *size = diopiSize_t(ptr->sizes().data(), ptr->dim());
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorStride(diopiConstTensorHandle_t pth, diopiSize_t* stride) {
    const at::Tensor* ptr = reinterpret_cast<const at::Tensor*>(pth);
    *stride = diopiSize_t(ptr->strides().data(), ptr->dim());
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorDtype(diopiConstTensorHandle_t pth, diopiDtype_t* dtype) {
    const at::Tensor* ptr = reinterpret_cast<const at::Tensor*>(pth);
    *dtype = dipu::diopi::toDiopiDtype(ptr->scalar_type());
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorDevice(diopiConstTensorHandle_t pth, diopiDevice_t* device) {
    const at::Tensor* ptr = reinterpret_cast<const at::Tensor*>(pth);
    *device = (ptr->is_cpu() ? diopi_host : diopi_device);
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorNumel(diopiConstTensorHandle_t pth, int64_t* numel) {
    if (pth == nullptr) {
        *numel = 0;
        return diopiSuccess;
    }

    const at::Tensor* ptr = reinterpret_cast<const at::Tensor*>(pth);
    *numel = ptr->numel();
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetTensorElemSize(diopiConstTensorHandle_t pth, int64_t* elemsize) {
    const at::Tensor* ptr = reinterpret_cast<const at::Tensor*>(pth);
    diopiDtype_t dtype;
    auto ret = diopiGetTensorDtype(pth, &dtype);
    if (ret != diopiSuccess) return ret;

    *elemsize = dipu::diopi::getElemSize(dtype);
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiGetStream(diopiContextHandle_t ctx, diopiStreamHandle_t* stream) {
    *stream = ctx->stream;
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiRequireTensor(
    diopiContextHandle_t ctx, diopiTensorHandle_t* tensor,
    const diopiSize_t* size, const diopiSize_t* stride,
    const diopiDtype_t dtype, const diopiDevice_t device) {
    at::IntArrayRef at_dims(size->data, size->len);
    caffe2::TypeMeta at_type = dipu::diopi::toATenType(dtype);
    c10::DeviceType at_device = dipu::diopi::toATenDevice(device);
    auto options = at::TensorOptions(at_device).dtype(at_type);

    int64_t numel = 0;
    diopiError_t ret = diopiGetTensorNumel(*tensor, &numel);
    if (ret != diopiSuccess) return ret;
    if (numel == 0) {
        at::Tensor t = at::empty(at_dims, options);
        if ((*tensor) == nullptr) {
            ctx->arrays.emplace_back(std::move(t));
            *tensor = reinterpret_cast<diopiTensorHandle_t>(&(ctx->arrays.back()));
        } else {
            *(reinterpret_cast<at::Tensor*>(*tensor)) = std::move(t);
        }
        return diopiSuccess;
    }

    void* data = nullptr;
    ret = diopiGetTensorData(tensor, &data);
    if (ret != diopiSuccess) return ret;
    at::Allocator* allocator = nullptr;
    at::IntArrayRef at_strides(stride->data, stride->len);
    at::Tensor t = dipu::diopi::fromPreAllocated(
        data, at_dims, at_strides, [](void*){}, allocator, options);
    if ((*tensor) == nullptr) {
        ctx->arrays.emplace_back(std::move(t));
        *tensor = reinterpret_cast<diopiTensorHandle_t>(&(ctx->arrays.back()));
    } else {
        *(reinterpret_cast<at::Tensor*>(*tensor)) = std::move(t);
    }
    return diopiSuccess;
}

DIOPI_RT_API diopiError_t diopiRequireBuffer(
    diopiContextHandle_t ctx, diopiTensorHandle_t* tensor,
    int64_t num_bytes, diopiDevice_t device) {
    diopiSize_t size(&num_bytes, 1);
    return diopiRequireTensor(ctx, tensor, &size, nullptr, diopi_dtype_int8, device);
}

}  // extern "C"