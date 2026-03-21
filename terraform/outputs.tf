output "server_ip" {
  description = "Public IPv4 address of the WODpilot VPS"
  value       = hcloud_server.wodpilot.ipv4_address
}

output "server_id" {
  description = "Hetzner server ID"
  value       = hcloud_server.wodpilot.id
}
