// Copyright 2014, Additive Regularization of Topic Models.

#include "artm/score_calculator_interface.h"

#include "artm/core/dictionary.h"
#include "artm/core/phi_matrix.h"

namespace artm {

std::shared_ptr< ::artm::core::Dictionary> ScoreCalculatorInterface::dictionary(
    const std::string& dictionary_name) {
  if (dictionaries_ == nullptr) {
      return nullptr;
  }

  return dictionaries_->get(dictionary_name);
}

void ScoreCalculatorInterface::set_dictionaries(
    const ::artm::core::ThreadSafeDictionaryCollection* dictionaries) {
  dictionaries_ = dictionaries;
}

}  // namespace artm
