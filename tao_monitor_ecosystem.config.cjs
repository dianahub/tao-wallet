module.exports = {
  apps: [
    {
      name: "tao-monitor",
      script: "/mnt/c/TAO_WALLET/tao_monitor.py",
      interpreter: "python3",
      cron_restart: "0 * * * *",
      autorestart: false,
      watch: false,
      out_file: "/mnt/c/TAO_WALLET/tao_monitor.log",
      error_file: "/mnt/c/TAO_WALLET/tao_monitor_err.log",
    },
    {
      name: "tao-advisor",
      script: "/mnt/c/TAO_WALLET/tao_advisor.py",
      interpreter: "python3",
      autorestart: true,
      watch: false,
      out_file: "/mnt/c/TAO_WALLET/tao_advisor.log",
      error_file: "/mnt/c/TAO_WALLET/tao_advisor_err.log",
    },
  ],
};
