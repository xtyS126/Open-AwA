/* APP 资源监控：每 30s 采样 CPU/内存/网络，持续 N 分钟
 * 用法：node scripts/monitor-app.cjs <分钟数>
 */
const { execSync } = require('child_process')
const ADB = 'D:/Android/Sdk/platform-tools/adb.exe'
const DEVICE = '127.0.0.1:5555'

const minutes = parseInt(process.argv[2] || '5', 10)
const samples = minutes * 2
console.log(`监控开始：${minutes} 分钟，每 30s 采样（共 ${samples} 次）`)

function getPid() {
  return execSync(`"${ADB}" -s ${DEVICE} shell pidof com.openawa.mobile`).toString().trim()
}

for (let i = 0; i < samples; i++) {
  try {
    const pid = getPid()
    if (!pid) { console.log(`[${i + 1}] APP 未运行`); break }
    // CPU: top 单次采样
    const top = execSync(`"${ADB}" -s ${DEVICE} shell "top -n 1 -b | grep ${pid}"`).toString().trim()
    const cpuMatch = top.match(/\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/)
    // 内存
    const mem = execSync(`"${ADB}" -s ${DEVICE} shell "dumpsys meminfo ${pid} | grep 'TOTAL PSS'"`).toString().trim()
    // 网络连接数（含 WebView 的 socket）
    const sockets = execSync(`"${ADB}" -s ${DEVICE} shell "cat /proc/${pid}/net/tcp | wc -l"`).toString().trim()
    console.log(`[${i + 1}] CPU%=${cpuMatch ? cpuMatch[1] : '?'} | ${mem} | tcp_conns=${sockets}`)
  } catch (e) {
    console.log(`[${i + 1}] 采样失败: ${e.message.split('\n')[0]}`)
  }
  const { execSync: sleep } = require('child_process')
  if (i < samples - 1) execSync('sleep 30')
}
console.log('监控结束')
