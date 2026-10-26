# Source/manual tools must not become a second owner of an installed machine.
# Presence is enough to refuse: this is not an ownership or health assertion.
$ticketboxMachineRoot = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'Ticketbox\machine'
$ticketboxInstalledServices = @(Get-Service -Name TicketboxBackend,TicketboxPg,TicketboxCloudflared -ErrorAction SilentlyContinue)
if ((Test-Path -LiteralPath $ticketboxMachineRoot -ErrorAction Stop) -or $ticketboxInstalledServices.Count -gt 0) {
    throw 'ticketbox_source_runtime_only: 此电脑已有小票夹安装或服务。请打开小票夹管理器查看状态和管理公网连接；旧源码运维脚本不能修改或代替该安装。'
}
