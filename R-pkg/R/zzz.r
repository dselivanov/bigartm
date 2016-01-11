.onLoad <- function(libname, pkgname) {
  messages_proto <- system.file("proto/messages.proto", package = "bigartm")
  RProtoBuf::readProtoFiles( messages_proto )
  # ls( "RProtoBuf:DescriptorPool" )
}

.onUnload <- function(libpath) {
  library.dynam.unload("bigartm", libpath)
}
