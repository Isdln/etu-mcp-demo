# VirtualBox
$env:Path += ";D:\VirtualBox"

VBoxManage createvm --name "pgmon-stand" --ostype Ubuntu24_LTS_64 --basefolder "D:\VirtualBox" --register
VBoxManage modifyvm "pgmon-stand" --cpus 4 --memory 16384 --cpuexecutioncap 100 --ioapic on --pae off --nested-hw-virt off --paravirtprovider kvm --vram 16 --graphicscontroller vmsvga --usb off --clipboard-mode disabled --nic1 nat --nictype1 virtio --rtcuseutc on
VBoxManage modifyvm "pgmon-stand" --natpf1 "ssh,tcp,127.0.0.1,2222,,22"
VBoxManage modifyvm "pgmon-stand" --natpf1 "clone,tcp,127.0.0.1,5434,,5434"

VBoxManage storagectl "pgmon-stand" --name "SATA" --add sata --controller IntelAhci --portcount 5 --bootable on --hostiocache off

VBoxManage createmedium disk --filename "D:\VirtualBox\pgmon-stand\system.vdi" --size 40960 --format VDI --variant Standard
VBoxManage createmedium disk --filename "D:\VirtualBox\pgmon-stand\pgdata.vdi" --size 81920 --format VDI --variant Fixed
VBoxManage createmedium disk --filename "D:\VirtualBox\pgmon-stand\pgmeta.vdi" --size 30720 --format VDI --variant Fixed

VBoxManage storageattach "pgmon-stand" --storagectl "SATA" --port 0 --device 0 --type hdd --medium "D:\VirtualBox\pgmon-stand\system.vdi" --nonrotational on
VBoxManage storageattach "pgmon-stand" --storagectl "SATA" --port 1 --device 0 --type hdd --medium "D:\VirtualBox\pgmon-stand\pgdata.vdi" --nonrotational on
VBoxManage storageattach "pgmon-stand" --storagectl "SATA" --port 2 --device 0 --type hdd --medium "D:\VirtualBox\pgmon-stand\pgmeta.vdi" --nonrotational on
VBoxManage storageattach "pgmon-stand" --storagectl "SATA" --port 4 --device 0 --type dvddrive --medium "D:\VirtualBox\iso\ubuntu-24.04.4-live-server-amd64.iso"

VBoxManage setextradata "pgmon-stand" "VBoxInternal/Devices/ahci/0/LUN#0/Config/IgnoreFlush" 0
VBoxManage setextradata "pgmon-stand" "VBoxInternal/Devices/ahci/0/LUN#1/Config/IgnoreFlush" 0
VBoxManage setextradata "pgmon-stand" "VBoxInternal/Devices/ahci/0/LUN#2/Config/IgnoreFlush" 0

VBoxManage startvm "pgmon-stand" --type gui

# Базовая настройка системы
sudo sed -i 's/^#$nrconf{restart}.*/$nrconf{restart} = "a";/' /etc/needrestart/needrestart.conf
sudo systemctl disable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer
sudo sed -i 's/"1"/"0"/g' /etc/apt/apt.conf.d/20auto-upgrades
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
sudo systemctl disable --now apport.service
sudo systemctl set-default multi-user.target

sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get -y install curl ca-certificates gnupg jq zstd git iproute2 sysstat parted python3-venv python3-dev

sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo tee /etc/sysctl.d/99-pgmon.conf >/dev/null <<'SYSCTL'
vm.swappiness = 10
vm.overcommit_memory = 2
vm.overcommit_ratio = 95
vm.dirty_background_ratio = 5
vm.dirty_ratio = 15
SYSCTL
sudo sysctl --system

sudo tee /etc/systemd/system/disable-thp.service >/dev/null <<'THP'
[Unit]
Description=Disable transparent huge pages
After=sysinit.target
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled'
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/defrag'
[Install]
WantedBy=multi-user.target
THP
sudo systemctl enable --now disable-thp.service

# Монтирование и разметка дисков
sudo parted -s /dev/sdb mklabel gpt mkpart primary ext4 0% 100%
sudo parted -s /dev/sdc mklabel gpt mkpart primary ext4 0% 100%
sudo mkfs.ext4 -L pgdata -m 0 -E lazy_itable_init=0,lazy_journal_init=0 /dev/sdb1
sudo mkfs.ext4 -L pgmeta -m 0 -E lazy_itable_init=0,lazy_journal_init=0 /dev/sdc1

sudo mkdir -p /mnt/pgdata /mnt/pgmeta
echo "UUID=$(sudo blkid -s UUID -o value /dev/sdb1) /mnt/pgdata ext4 defaults,noatime,nodiratime 0 2" | sudo tee -a /etc/fstab
echo "UUID=$(sudo blkid -s UUID -o value /dev/sdc1) /mnt/pgmeta ext4 defaults,noatime,nodiratime 0 2" | sudo tee -a /etc/fstab
sudo mount -a

# Docker установка
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker isd

sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" },
  "default-ulimits": { "nofile": { "Name": "nofile", "Soft": 4096, "Hard": 8192 } }
}
EOF
sudo systemctl restart docker

# Загрузка файлов проекта
sudo mkdir -p /opt/pgmon-stand && sudo chown isd:isd /opt/pgmon-stand
git clone https://github.com/Isdln/etu-mcp-demo.git /opt/pgmon-stand
cd /opt/pgmon-stand
chmod +x stand/scripts/*.sh stand/scripts/faults/*.sh stand/pgbench/*.sh
# После загрузки необходимо создать файл .env

# Docker настройка
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/mounts.conf >/dev/null <<'UNIT'
[Unit]
RequiresMountsFor=/mnt/pgdata /mnt/pgmeta
UNIT
sudo systemctl daemon-reload

sudo tee /etc/udev/rules.d/90-pgmon-scheduler.rules >/dev/null <<'UDEV'
ACTION=="add|change", KERNEL=="sd[b-c]", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="sd[b-c]", ATTR{queue/read_ahead_kb}="256"
UDEV
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=block

# Права и директории
sudo mkdir -p /opt/pgmon-stand/conf
sudo mkdir -p /opt/pgmon-stand/audit
sudo mkdir -p /opt/pgmon-stand/log/primary
sudo mkdir -p /opt/pgmon-stand/log/replica
sudo mkdir -p /mnt/pgdata/primary
sudo mkdir -p /mnt/pgdata/replica
sudo mkdir -p /mnt/pgdata/clone
sudo mkdir -p /mnt/pgmeta/meta
sudo mkdir -p /mnt/pgmeta/snapshots
sudo mkdir -p /mnt/pgmeta/bundles
sudo mkdir -p /mnt/pgmeta/archive

sudo chown -R isd:isd /opt/pgmon-stand
sudo chown -R 999:999 /mnt/pgdata/primary
sudo chown -R 999:999 /mnt/pgdata/replica
sudo chown -R 999:999 /mnt/pgdata/clone
sudo chown -R 999:999 /mnt/pgmeta/meta
sudo chown 999:999 /mnt/pgmeta/archive
sudo chown 999:999 /mnt/pgmeta/snapshots
sudo chown -R 999:999 /opt/pgmon-stand/log/primary
sudo chown -R 999:999 /opt/pgmon-stand/log/replica
sudo chown -R isd:isd /mnt/pgmeta/bundles

sudo chmod 700 /mnt/pgdata/primary
sudo chmod 700 /mnt/pgdata/replica
sudo chmod 700 /mnt/pgdata/clone
sudo chmod 700 /mnt/pgmeta/meta
sudo chmod 755 /mnt/pgmeta/archive
sudo chmod 755 /mnt/pgmeta/snapshots

ln -sfn /mnt/pgmeta/bundles /opt/pgmon-stand/bundles
ln -sfn /mnt/pgmeta/snapshots /opt/pgmon-stand/snapshots

# Создание контейнеров
cd /opt/pgmon-stand
docker build -f stand/Dockerfile.pg -t pgmon/postgres:18 stand/
docker compose up -d primary meta
docker compose ps

# Настройка PostgreSQL
docker cp sql/primary_setup.sql pgmon-primary:/tmp/
docker exec -it pgmon-primary psql -U postgres -d bench -f /tmp/primary_setup.sql

set -a; source .env; set +a
docker exec -i pgmon-primary psql -U postgres -d bench <<EOF
ALTER ROLE pgmon_collector PASSWORD '$COLLECTOR_PASSWORD';
ALTER ROLE pgmon_operator  PASSWORD '$OPERATOR_PASSWORD';
CREATE ROLE app LOGIN PASSWORD '$APP_PASSWORD';
GRANT ALL ON DATABASE bench TO app;
GRANT ALL ON SCHEMA public TO app;
ALTER SCHEMA public OWNER TO app;
CREATE ROLE replicator REPLICATION LOGIN PASSWORD '$REPLICATOR_PASSWORD';
EOF

docker exec -i pgmon-primary bash -c "grep -q replicator /var/lib/postgresql/data/pgdata/pg_hba.conf || echo 'host replication replicator all md5' >> /var/lib/postgresql/data/pgdata/pg_hba.conf"
docker exec -it pgmon-primary psql -U postgres -c "SELECT pg_reload_conf();"

docker cp sql/meta_schema.sql pgmon-meta:/tmp/
docker exec -it pgmon-meta psql -U postgres -d pgmon_meta -f /tmp/meta_schema.sql
docker exec -it pgmon-primary psql -U postgres -d bench -c "\du"

# Установка проекта
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -e .

# Установка HammerDB создание и наполнение базы
sudo wget https://github.com/TPC-Council/HammerDB/releases/download/v6.0/HammerDB-6.0-Prod-Lin-UBU24.tar.gz
sudo tar xzf HammerDB-6.0-Prod-Lin-UBU24.tar.gz && sudo mv HammerDB-6.0 HammerDB
sudo chown -R isd:isd /opt/HammerDB
echo 'export HAMMERDB_HOME=/opt/HammerDB' >> ~/.bashrc
rm -f /tmp/hammer.DB
set -a; source /opt/pgmon-stand/.env; set +a
cd /opt/HammerDB
./hammerdbcli auto /opt/pgmon-stand/stand/build_schema.tcl
cd /opt/pgmon-stand
./stand/scripts/prepare_db.sh

# Создание реплики
set -a; source .env; set +a
docker run --rm --network pgmon-stand_stand -v /mnt/pgdata/replica:/target -e PGPASSWORD="$REPLICATOR_PASSWORD" pgmon/postgres:18 pg_basebackup -h primary -U replicator -D /target/pgdata -X stream -C -S replica_main -R -P --checkpoint=fast

sudo chown -R 999:999 /mnt/pgdata/replica
sudo chmod 700 /mnt/pgdata/replica
docker compose up -d replica pgbouncer
sleep 25
docker exec -it pgmon-primary psql -U postgres -c "SELECT application_name, state FROM pg_stat_replication;"