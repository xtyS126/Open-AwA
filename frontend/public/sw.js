'use strict'

/* global self, caches */

const RETIRED_CACHE_NAME = 'anime-blog-v4'

self.addEventListener('install', (event) => {
  // 退役脚本必须立即进入激活阶段，不能继续等待旧页面退出。
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // 仅删除抓包确认的历史缓存，避免影响其他仍在使用的缓存。
    await caches.delete(RETIRED_CACHE_NAME)

    // 注销成功后只刷新当前同源窗口一次，使页面脱离旧 worker 控制。
    const unregistered = await self.registration.unregister()
    if (!unregistered) {
      return
    }

    const windowClients = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    })
    await Promise.all(windowClients.map((client) => {
      if (typeof client.navigate !== 'function') {
        return Promise.resolve()
      }
      return client.navigate(client.url)
    }))
  })())
})
