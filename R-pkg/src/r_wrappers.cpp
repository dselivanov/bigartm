#include "r_interface.h"

using namespace std;
using namespace Rcpp;

typedef struct {
  uint byte_size;
  const char * ptr;
} MSG;

MSG get_msg_meta(RawVector msg_ser) {
  MSG msg;
  msg.byte_size = msg_ser.size();
  msg.ptr = (char *)&(*msg_ser.begin());
  return msg;
}

//' @export
// [[Rcpp::export]]
Int32 R_ArtmCreateMasterComponent(RawVector master_component_config) {
//   MSG msg = get_msg_meta(master_component_config);
//   return( ArtmCreateMasterComponent(msg.byte_size,  msg.ptr ) );
  const char * ptr = (char *)&(*master_component_config.begin());
  return( ArtmCreateMasterComponent(master_component_config.size(),  ptr ) );
}

//' @export
// [[Rcpp::export]]
Int32 R_ArtmCreateDictionary(Int32 master_id, RawVector dict_component_config) {
//   MSG msg = get_msg_meta(dict_component_config);
//   return( ArtmCreateDictionary(master_id, msg.byte_size,  msg.ptr ) );
  const char * ptr = (char *)&(*dict_component_config.begin());
  return( ArtmCreateDictionary(master_id, dict_component_config.size(),  ptr ) );
}

