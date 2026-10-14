import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import HealthPanel from './components/HealthPanel';
import Tasks from './pages/Tasks';
import Approvals from './pages/Approvals';
import Sandbox from './pages/Sandbox';

const pages = [
  { path: '/', name: 'Dashboard', icon: '◈', desc: '环境状态与阶段概览' },
  { path: '/chat', name: 'AI Chat', icon: '◇', desc: '模型对话将在后续阶段实现' },
  { path: '/tasks', name: 'Agent Tasks', icon: '▤', desc: '持久化 Mock 协作与执行轨迹' },
  { path: '/models', name: 'Model Center', icon: '⬡', desc: '四个独立模型配置槽位' },
  { path: '/sandbox', name: 'Sandbox Center', icon: '▣', desc: '经独立审批的真实 Docker 执行与审计' },
  { path: '/mcp', name: 'MCP Tools', icon: '⌘', desc: '工具网关将在后续阶段实现' },
  { path: '/skills', name: 'Skills Center', icon: '✦', desc: '技能版本与管理将在后续阶段实现' },
  { path: '/approvals', name: 'Approval Center', icon: '✓', desc: '持久化计划确认与审批记录' },
  { path: '/observability', name: 'Observability', icon: '▥', desc: '模型用量与费用统计尚未实现' },
  { path: '/settings', name: 'Settings', icon: '⚙', desc: '本地开发环境与配置说明' },
];

function Placeholder({ name, desc }: { name: string; desc: string }) {
  return <section className="panel empty-state"><div className="empty-icon">◇</div><span className="badge">功能开发中</span><h2>{name}</h2><p>{desc}</p><p className="muted">当前阶段尚未开放此功能。此页面没有运行数据。</p></section>;
}

function Models() {
  const roles = [{ name: 'Planner', desc: '复杂任务规划与依赖分析' }, { name: 'Coder', desc: '代码与工具调用决策' }, { name: 'Researcher', desc: '检索、文档理解与 RAG' }, { name: 'Reviewer', desc: '质量审查与反馈' }];
  return <><div className="notice">P1 已实现服务端配置结构、校验和受保护存储接口。此页展示槽位定义，未读取配置。真实模型调用尚未开放。任务页仅支持显式 Mock。</div><div className="model-grid">{roles.map(role => <section className="panel model-card" key={role.name}><span className="eyebrow">MODEL SLOT</span><h2>{role.name}</h2><p>{role.desc}</p><dl><dt>配置状态</dt><dd>未读取</dd><dt>调用能力</dt><dd>功能开发中</dd><dt>凭据方式</dt><dd>服务端受保护引用</dd></dl></section>)}</div></>;
}

function Dashboard() {
  return <><div className="welcome"><div><span className="eyebrow">SANDBOX / PHASE 03</span><h2>构建可验证的 AI 工作空间</h2><p>真实 Docker 沙箱与持久化协作流程已建立。模型响应仍为明确的 Mock。</p></div><div className="phase-mark">P3<span>SANDBOX</span></div></div><HealthPanel /><div className="dashboard-grid"><section className="panel"><span className="eyebrow">CURRENT SCOPE</span><h2>当前可用</h2><ul className="feature-list"><li>FastAPI 健康接口与 OpenAPI</li><li>PostgreSQL 与 Redis 真实连接检查</li><li>四模型配置与服务端校验</li><li>持久化工作流、人工审批与 SSE</li><li>经独立审批的受限 Docker 执行</li></ul></section><section className="panel"><span className="eyebrow">SCOPE BOUNDARY</span><h2>当前范围与安全边界</h2><p>模型回答保持 Mock。Sandbox Center 展示真实 Docker 任务；真实模型、MCP 和 Skills 执行尚未开放。</p><NavLink className="text-link" to="/sandbox">查看沙箱执行 →</NavLink></section></div></>;
}

export default function App() {
  const location = useLocation();
  const active = pages.find(page => page.path === location.pathname) || pages[0];
  return <div className="app-shell"><aside className="sidebar"><NavLink to="/" className="brand"><span className="brand-icon">A</span><div>AgentForge<span>AI WORKSPACE</span></div></NavLink><span className="nav-section">工作空间</span><nav aria-label="主导航">{pages.map(page => <NavLink end={page.path === '/'} to={page.path} key={page.path}><span aria-hidden="true">{page.icon}</span>{page.name}</NavLink>)}</nav><div className="sidebar-foot"><span className="badge">P3 · 本地开发</span><p>Mock 协作 · 真实 Docker</p></div></aside><main><header><div><span className="eyebrow">AGENTFORGE AI</span><h1>{active.name}</h1></div><span className="environment"><span/>LOCAL DEVELOPMENT</span></header><div className="content"><Routes><Route path="/" element={<Dashboard/>}/><Route path="/models" element={<Models/>}/><Route path="/tasks" element={<Tasks/>}/><Route path="/approvals" element={<Approvals/>}/><Route path="/sandbox" element={<Sandbox/>}/><Route path="/settings" element={<><HealthPanel/><section className="panel"><h2>配置与安全边界</h2><p>端口由项目 .env 配置。前端通过同源代理访问后端，秘密环境变量不会打包到浏览器。</p><p>配置管理接口使用本地管理员 Bearer Token；任务和审批页支持当前页面内存授权；不提供模型密钥输入表单。</p></section></>}/>{pages.filter(p => !['/', '/models', '/settings', '/tasks', '/approvals', '/sandbox'].includes(p.path)).map(page => <Route key={page.path} path={page.path} element={<Placeholder name={page.name} desc={page.desc}/>}/>)}<Route path="*" element={<Navigate to="/" replace/>}/></Routes><footer>AgentForge AI · P3 沙箱阶段 <span>真实状态 · 明确边界</span></footer></div></main></div>;
}
