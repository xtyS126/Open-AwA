/**
 * 跳过导航链接组件
 * 为键盘用户提供快速跳转到主内容的入口
 */
export function SkipLink() {
  return (
    <a href="#main-content" className="skip-link">
      跳转到主内容
    </a>
  )
}
