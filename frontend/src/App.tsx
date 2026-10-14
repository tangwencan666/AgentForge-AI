import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import HealthPanel from './components/HealthPanel';

const pages = [
  { path: '/', name: 'Dashboard', icon: '◈', desc: '环境状态与阶段概览' },
  { path: '/chat', name: 'AI Chat', icon: '◇', desc: '模型对话将在后续阶段实现' },
  { path: '/tasks', name: 'Agent Tasks', icon: '▤', desc: '任务规划与协作将在 P2 实现' },
  { path: '/models', name: 'Model Center', icon: '⬡', desc: '四个独立模型配置槽位' },
  { path: '/sandbox', name: 'Sandbox Center', icon: '▣', desc: 'Docker 执行与预热将在 P3 实现' },
  { path: '/mcp', name: 'MCP Tools', icon: '⌘', desc: '工具网关将在后续阶段实现' },
  { path: '/skills', name: 'Skills Center', icon: '✦', desc: '技能版本与管理将在后续阶段实现' },
  { path: '/approvals', name: 'Approval Center', icon: '✓', desc: '人工审批将在后续阶段实现' },
  { path: '/observability', name: 'Observability', icon: '▥', desc: '模型用量与费用统计尚未实现' },
  { path: '/settings', name: 'Settings', icon: '⚙', desc: '本地开发环境与配置说明' },
];

function Placeholder({ name, desc }: { name: string; desc: string }) {
  return <section className="panel empty-state"><div className="empty-icon">◇</div><span className="badge">功能开发中</span><h2>{name}</h2><p>{desc}</p><p className="muted">P1 仅建立项目基础。此页面没有真实执行记录，也没有模拟运行数据。</p></section>;
}

function Models() {
  const roles = [{ name: 'Planner', desc: '复杂任务规划与依赖分析' }, { name: 'Coder', desc: '代码与工具调用决策' }, { name: 'Researcher', desc: '检索、文档理解与 RAG' }, { name: 'Reviewer', desc: '质量审查与反馈' }];
  return <><div className="notice">P1 已实现服务端配置结构、校验和受保护存储接口。此页展示槽位定义，未读取配置。模型调用尚未实现。</div><div className="model-grid">{roles.map(role => <section className="panel model-card" key={role.name}><span className="eyebrow">MODEL SLOT</span><h2>{role.name}</h2><p>{role.desc}</p><dl><dt>配置状态</dt><dd>未读取</dd><dt>调用能力</dt><dd>功能开发中</dd><dt>凭据方式</dt><dd>服务端受保护引用</dd></dl></section>)}</div></>;
}

function Dashboard() {
  return <><div className="welcome"><div><span className="eyebrow">FOUNDATION / PHASE 01</span><h2>构建可验证的 AI 工作空间</h2><p>项目骨架已建立。先确认服务状态，再进入下一阶段。</p></div><div className="phase-mark">P1<span>FOUNDATION</span></div></div><HealthPanel /><div className="dashboard-grid"><section className="panel"><span className="eyebrow">CURRENT SCOPE</span><h2>当前可用</h2><ul className="feature-list"><li>FastAPI 健康接口与 OpenAPI</li><li>PostgreSQL 与 Redis 真实连接检查</li><li>四模型配置与服务端校验</li><li>请求 ID 与安全日志</li></ul></section><section className="panel"><span className="eyebrow">NEXT PHASE</span><h2>等待下一阶段批准</h2><p>Agent 协作、模型调用、沙箱、MCP 和 Skills 执行尚未实现。</p><NavLink className="text-link" to="/models">查看四模型槽位 →</NavLink></section></div></>;
}

export default function App() {
  const location = useLocation();
  const active = pages.find(page => page.path === location.pathname) || pages[0];
  return <div className="app-shell"><aside className="sidebar"><NavLink to="/" className="brand"><span className="brand-icon">A</span><div>AgentForge<span>AI WORKSPACE</span></div></NavLink><span className="nav-section">工作空间</span><nav aria-label="主导航">{pages.map(page => <NavLink end={page.path === '/'} to={page.path} key={page.path}><span aria-hidden="true">{page.icon}</span>{page.name}</NavLink>)}</nav><div className="sidebar-foot"><span className="badge">P1 · 本地开发</span><p>执行能力尚未启用</p></div></aside><main><header><div><span className="eyebrow">AGENTFORGE AI</span><h1>{active.name}</h1></div><span className="environment"><span/>LOCAL DEVELOPMENT</span></header><div className="content"><Routes><Route path="/" element={<Dashboard/>}/><Route path="/models" element={<Models/>}/><Route path="/settings" element={<><HealthPanel/><section className="panel"><h2>配置与安全边界</h2><p>端口由项目 .env 配置。前端通过同源代理访问后端，秘密环境变量不会打包到浏览器。</p><p>配置管理接口使用本地管理员 Bearer Token；P1 暂不提供浏览器登录或密钥输入表单。</p></section></>}/>{pages.filter(p => !['/', '/models', '/settings'].includes(p.path)).map(page => <Route key={page.path} path={page.path} element={<Placeholder name={page.name} desc={page.desc}/>}/>)}<Route path="*" element={<Navigate to="/" replace/>}/></Routes><footer>AgentForge AI · P1 基础阶段 <span>真实状态 · 明确边界</span></footer></div></main></div>;
}
