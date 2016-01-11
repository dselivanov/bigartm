# message MasterComponentConfig {
#   optional string disk_path = 2;
#   repeated Stream stream = 3;
#   optional bool compact_batches = 4 [default = true];
#   optional bool cache_theta = 5 [default = false];
#   optional int32 processors_count = 6;
#   optional int32 processor_queue_max_size = 7 [default = 10];
#   optional int32 merger_queue_max_size = 8 [default = 10];
#   repeated ScoreConfig score_config = 9;
#   optional bool online_batch_processing = 13 [default = false];  // obsolete in BigARTM v0.5.8
#   optional string disk_cache_path = 15;
# }

#' @export
artm_master_conf <- function(path) {
  master_conf <- new(artm.MasterComponentConfig,
                     disk_path = path)

  master_conf
}

#' @export
artm_create_mater <- function(master_config) {

  stopifnot(inherits(master_config, 'Message') &&
              master_config@type == 'artm.MasterComponentConfig')

  mc <- new(artm.MasterComponentConfig, master_config)

  R_ArtmCreateMasterComponent(mc$serialize(NULL))
}

