/* avoid remapping of Rf_<function> to <function> in R header files */
#ifndef R_NO_REMAP
#define R_NO_REMAP
#endif /* R_NO_REMAP */

/* use strict R headers */
#ifndef STRICT_R_HEADERS
#define STRICT_R_HEADERS
#endif /* STRICT_R_HEADERS */


#include "c_interface.h"
#include <Rcpp.h>

using namespace std;
using namespace Rcpp;

int R_ArtmCreateMasterComponentR(int length, RawVector master_component_config);
