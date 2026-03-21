variable "hcloud_token" {
  description = "Hetzner Cloud API token (read/write)"
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "SSH public key to deploy to the server (e.g. contents of ~/.ssh/id_ed25519.pub)"
  type        = string
}

variable "server_name" {
  description = "Name of the Hetzner server"
  type        = string
  default     = "wodpilot"
}

variable "server_type" {
  description = "Hetzner server type"
  type        = string
  default     = "cx21"
}

variable "location" {
  description = "Hetzner datacenter location (nbg1, fsn1, hel1, ash, hil)"
  type        = string
  default     = "nbg1"
}
