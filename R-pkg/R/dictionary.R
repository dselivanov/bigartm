
# // Represents a static dictionary.
# message DictionaryData {
#   optional string name = 1;
#   repeated string token = 2;
#   repeated string class_id = 3;
#   repeated float token_value = 4;  // for scores and regularizers
#   repeated float token_tf = 5;  // token frequency
#   repeated float token_df = 6;  // number of document occurences
#   repeated int32 cooc_first_index = 7;
#   repeated int32 cooc_second_index = 8;
#   repeated float cooc_value = 9;
# }

#' @export
artm_dict_conf <- function(tokens, # words
                           token_counts,
                           dict_name,
                           doc_count = NULL,
                           class_ids = NULL,
                           token_dfs = NULL,
                           token_values = NULL,
                           tcm = NULL # term-cooccurence matrix
                           ) {

  if (is.null(doc_count) || is.null(token_dfs))
    token_values = NULL
  else
    token_dfs / doc_count

  dict_conf <- new(artm.DictionaryData,
            name = dict_name,
            token = tokens,
            class_id = class_ids,
            token_value = token_values,
            token_tf = token_counts,
            token_df = token_dfs)

  if ( !is.null(tcm) && !inherits(tcm, 'dgTMatrix')) {
    tcm <- as(tcm, 'dgTMatrix')
    dict_conf[['cooc_first_index']] <- tcm@i
    dict_conf[['cooc_second_index']] <- tcm@j
    dict_conf[['cooc_value']] <- tcm@x
  }

  dict_conf
}

#' @export
artm_create_dict <- function(master_id, dictionary_config) {

  stopifnot(inherits(dictionary_config, 'Message') &&
              dictionary_config@type == 'artm.DictionaryData')

  R_ArtmCreateDictionary(master_id, dictionary_config$serialize(NULL))
}

