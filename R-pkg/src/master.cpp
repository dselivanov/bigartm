#include <Rcpp.h>
#include "r_interface.h"

using namespace std;
using namespace Rcpp;

// [[Rcpp::export]]
int R_ArtmCreateMasterComponent(int length, RawVector master_component_config) {
  const char * ptr = (char *)&(*master_component_config.begin());
  return( ArtmCreateMasterComponent(length,  ptr ) );
}
