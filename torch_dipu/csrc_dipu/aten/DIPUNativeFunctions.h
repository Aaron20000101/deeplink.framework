# pragma once

#include <ATen/Tensor.h>
#include <ATen/ATen.h>

namespace dipu::native {

struct DIPUNativeFunctions {
    static at::Tensor add(const at::Tensor& self, const at::Tensor& other, const at::Scalar& alpha);
    static at::Tensor relu(const at::Tensor& self);
    static at::Tensor& relu_(at::Tensor& self);
    static ::std::tuple<at::Tensor,at::Tensor,at::Tensor> native_batch_norm(
        const at::Tensor & input, const c10::optional<at::Tensor> & weight,
        const c10::optional<at::Tensor> & bias,
        const c10::optional<at::Tensor> & running_mean,
        const c10::optional<at::Tensor> & running_var,
        bool training, double momentum, double eps);
};

}  // namespace dipu::native