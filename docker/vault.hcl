storage "file" {
  path = "/vault/data"
}

# Dis erisim kapali (compose ports yok); ic ag bot -> http://vault:8200
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

ui            = true
disable_mlock = true
api_addr      = "http://vault:8200"
