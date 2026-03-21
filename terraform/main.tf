terraform {
  required_version = ">= 1.6"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.49"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

# ── SSH Key ──────────────────────────────────────────────────────────────────

resource "hcloud_ssh_key" "wodpilot" {
  name       = "${var.server_name}-deploy"
  public_key = var.ssh_public_key
}

# ── Firewall ─────────────────────────────────────────────────────────────────

resource "hcloud_firewall" "wodpilot" {
  name = "${var.server_name}-firewall"

  rule {
    direction  = "in"
    port       = "22"
    protocol   = "tcp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    port       = "80"
    protocol   = "tcp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    port       = "443"
    protocol   = "tcp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

# ── Server ───────────────────────────────────────────────────────────────────

resource "hcloud_server" "wodpilot" {
  name         = var.server_name
  server_type  = var.server_type
  image        = "ubuntu-24.04"
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.wodpilot.id]
  firewall_ids = [hcloud_firewall.wodpilot.id]
  user_data    = file("${path.module}/cloud-init.yaml")

  labels = {
    app = "wodpilot"
  }
}
