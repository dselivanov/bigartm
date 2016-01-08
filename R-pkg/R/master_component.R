# create_mater_component('~/Downloads/bigartm/test_data/vw_data.txt')
create_mater_component <- function(disk_path) {
  mc <- new(artm.MasterComponentConfig, disk_path)
  return(ArtmCreateMasterComponentR(bytesize(mc),  mc$serialize(NULL)))
}

