.onLoad <- function(libname, pkgname) {
  messages_proto <- system.file("include/artm/messages.proto", package = "bigartm")
  RProtoBuf::readProtoFiles( messages_proto )
}

.onUnload <- function(libpath) {
  library.dynam.unload("bigartm", libpath)
}
