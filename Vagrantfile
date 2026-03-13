Vagrant.configure("2") do |config|

  config.vm.box = "ubuntu/jammy64"
  config.vm.hostname = "devops-koffeecart"

  config.vm.network "forwarded_port", guest: 80, host: 8080 #nginx
  config.vm.network "forwarded_port", guest: 8000, host: 8000 #gunicorn
  config.vm.synced_folder ".", "/home/vagrant/projects/koffeecart"

  config.vm.provider "virtualbox" do |vb|
    vb.memory = "2048"
    vb.cpus = 2
    vb.name = "devops-koffeecart"
  end
  config.vm.provision "shell", inline: <<-SHELL
    apt-get update -y
    apt-get install -y \
      git \
      curl \
      wget \
      vim \
      net-tools \
      ca-certificates \
      gnupg \
      lsb-release

# Cài Docker
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

usermod -aG docker vagrant

systemctl enable docker
systemctl start docker

docker --version

SHELL
end


