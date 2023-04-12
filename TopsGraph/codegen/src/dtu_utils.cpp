#include "dtu_utils.h"

#include <iostream>
#include <unistd.h>

bool file_exists(const char *filename) { return (access(filename, 0) == 0); }

void compile(std::shared_ptr<builder::Builder> builder,
             topsExecutable_t *exe_ptr) {
  topsgraphProgram program;
  // get the built IR from builder
  auto hlir_module = builder->GetModule();
  auto ret = topsgraphCreateProgramFromModule(&program, hlir_module.get());
  /*const char *options[] = {"-arch=gcu210", "-resource=1c4s",
                           "-hlir=tops-hlir-pipeline"};*/
  const char *options[] = {"-arch=gcu200", "-resource=4c24s",
                           "-hlir=tops-hlir-pipeline"};
  topsgraphCompileProgram(program, 3, options);
  // get binary size and binary data
  size_t binary_size = 0;
  topsgraphGetBinSize(program, &binary_size);
  char *binary = new char[binary_size];
  topsgraphGetBin(program, binary);
  topsCreateExecutable(exe_ptr, binary, binary_size);
  delete [] binary;
  topsgraphDestroyProgram(&program);
  return;
}

int run(topsExecutable_t exe_ptr, std::vector<void *> &input_ptrs,
        std::vector<void *> &output_ptrs) {
  int device_id = 3;
  int count = 0;
  void *inputs[MAX_NUM] = {0};
  void *outputs[MAX_NUM] = {0};
  void *dev_input = nullptr;
  void *dev_output = nullptr;
  topsError_t ret;
  topsStream_t stream;
  topsResource_t res_bundle;

  // 1. init device
  if (topsGetDevice(&device_id) != topsSuccess) {
    topsGetDeviceCount(&count);
    if (count != topsSuccess) {
      topsSetDevice(device_id);
    }
  }
  topsStreamCreate(&stream);
  topsCreateResourceForExecutable(&res_bundle, exe_ptr);

  // 2.1 query InputCount,output_count
  uint64_t input_count = 0, output_count = 0;
  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoInputCount,
                                    &input_count),
            topsSuccess);
  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoOutputCount,
                                    &output_count),
            topsSuccess);
  // 2.2 query InputSize,output_size
  uint64_t *input_size = (uint64_t *)malloc(input_count * sizeof(uint64_t));
  EXPECT_NE(input_size, nullptr);
  uint64_t *output_size = (uint64_t *)malloc(output_count * sizeof(uint64_t));
  EXPECT_NE(output_size, nullptr);

  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoInputSizeList,
                                    input_size),
            topsSuccess);
  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoOutputSizeList,
                                    output_size),
            topsSuccess);

  // 3. prepare data, H2D
  for (size_t i = 0; i < input_count; i++) {
    topsMallocForResource(&dev_input, input_size[i], res_bundle);
    topsMemcpyAsync(dev_input, input_ptrs[i], input_size[i],
                    topsMemcpyHostToDevice, stream);
    inputs[i] = dev_input;
  }

  for (size_t i = 0; i < output_count; i++) {
    topsMallocForResource(&dev_output, output_size[i], res_bundle);
    outputs[i] = dev_output;
  }


  // 4. run

  ret = topsLaunchExecutableV2(exe_ptr, res_bundle, inputs, input_count,
		  nullptr, nullptr,
                               outputs, output_count, stream);
  if (ret != topsSuccess) {
    std::cout << "topsLaunchExecutable fail,  ret = " << ret << std::endl;
    return -1;
  }
  uint64_t *output_rank_list =
      (uint64_t *)malloc(sizeof(uint64_t) * output_count);
  ret = topsExecutableQueryInfo(exe_ptr, topsExecutableInfoOutputRank,
                                output_rank_list);
  if (ret != topsSuccess) {
    std::cout << "topsExecutableQueryInfo for OutputRank fail,  ret = " << ret
              << std::endl;
    return -1;
  }
  uint64_t output_dims_size = 0;
  for (int i = 0; i < output_count; i++) {
    output_dims_size += output_rank_list[i];
  }
  uint64_t *output_dim_list =
      (uint64_t *)malloc(sizeof(uint64_t) * output_dims_size);
  ret = topsExecutableQueryInfo(exe_ptr, topsExecutableInfoOutputDimsList,
                                output_dim_list);
  if (ret != topsSuccess) {
    std::cout << "topsExecutableQueryInfo for OutputDimsList fail,  ret = "
              << ret << std::endl;
    return -1;
  }
  uint64_t dim_index = 0;
  for (size_t i = 0; i < output_count; i++) {
    std::vector<uint64_t> shape_v;
    for (size_t j = 0; j < output_rank_list[i]; j++) {
      shape_v.push_back(output_dim_list[dim_index++]);
    }
    // 5. D2H
    ret = topsMemcpyAsync(output_ptrs[i], outputs[i], output_size[i],
                          topsMemcpyDeviceToHost, stream);
    if (ret != 0) {
      std::cout << "topsMemcpyAsync fail,  ret = " << ret << std::endl;
      return -1;
    }
    topsStreamSynchronize(stream);
  }

  // 6. release data
  for (size_t i = 0; i < input_count; i++) {
    topsFree(inputs[i]);
  }
  for (size_t i = 0; i < output_count; i++) {
    topsFree(outputs[i]);
  }
  topsStreamDestroy(stream);
  topsDestroyExecutable(exe_ptr);
  topsDestroyResource(res_bundle);
  return 0;
}

int runV2(topsExecutable_t exe_ptr, std::vector<void *> &input_ptrs,
          size_t *input_dims, size_t *input_rank,
          std::vector<void *> &output_ptrs, size_t *output_dims,
          size_t *output_rank) {
  int device_id = 0;
  int count = 0;
  void *inputs[MAX_NUM] = {0};
  void *outputs[MAX_NUM] = {0};
  void *dev_input = nullptr;
  void *dev_output = nullptr;
  topsError_t ret;
  topsStream_t stream;
  topsResource_t res_bundle;

  // 1. init device
  if (topsGetDevice(&device_id) != topsSuccess) {
    topsGetDeviceCount(&count);
    if (count != topsSuccess) {
      topsSetDevice(device_id);
    }
  }
  topsStreamCreate(&stream);
  topsCreateResourceForExecutable(&res_bundle, exe_ptr);

  // 2.1 query InputCount,output_count
  uint64_t input_count = 0, output_count = 0;
  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoInputCount,
                                    &input_count),
            topsSuccess);
  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoOutputCount,
                                    &output_count),
            topsSuccess);
  // 2.2 query InputSize,output_size
  uint64_t *input_size = (uint64_t *)malloc(input_count * sizeof(uint64_t));
  EXPECT_NE(input_size, nullptr);
  uint64_t *output_size = (uint64_t *)malloc(output_count * sizeof(uint64_t));
  EXPECT_NE(output_size, nullptr);

  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoInputSizeList,
                                    input_size),
            topsSuccess);
  EXPECT_EQ(topsExecutableQueryInfo(exe_ptr, topsExecutableInfoOutputSizeList,
                                    output_size),
            topsSuccess);

  // 3. prepare data, H2D
  for (size_t i = 0; i < input_count; i++) {
    topsMallocForResource(&dev_input, input_size[i], res_bundle);
    topsMemcpyAsync(dev_input, input_ptrs[i], input_size[i],
                    topsMemcpyHostToDevice, stream);
    inputs[i] = dev_input;
  }

  for (size_t i = 0; i < output_count; i++) {
    topsMallocForResource(&dev_output, output_size[i], res_bundle);
    outputs[i] = dev_output;
  }

  // 4. run
  ret = topsLaunchExecutableV2(exe_ptr, res_bundle, inputs, input_count,
                               input_dims, input_rank, outputs, output_count,
                               // output_dims, output_rank,
			       stream);
  if (ret != topsSuccess) {
    std::cout << "topsLaunchExecutable fail,  ret = " << ret << std::endl;
    return -1;
  }

  uint64_t dim_index = 0;
  for (size_t i = 0; i < output_count; i++) {
    // get real output shape
    uint64_t output_dim_size = 1; // should be the byte size of output data type
    std::vector<uint64_t> shape_v;
    for (size_t j = 0; j < output_rank[i]; j++) {
      shape_v.push_back(output_dims[dim_index]);
      output_dim_size *= output_dims[dim_index];
      ++dim_index;
    }
    // 5. D2H
    ret = topsMemcpyAsync(output_ptrs[i], outputs[i], output_size[i],
                          topsMemcpyDeviceToHost, stream);
    if (ret != 0) {
      std::cout << "topsMemcpyAsync fail,  ret = " << ret << std::endl;
      return -1;
    }
    topsStreamSynchronize(stream);
  }

  // 6. release data
  for (size_t i = 0; i < input_count; i++) {
    topsFree(inputs[i]);
  }
  for (size_t i = 0; i < output_count; i++) {
    topsFree(outputs[i]);
  }
  topsStreamDestroy(stream);
  topsDestroyExecutable(exe_ptr);
  topsDestroyResource(res_bundle);
  return 0;
}
