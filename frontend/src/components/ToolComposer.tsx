import { useState } from 'react';
import { capabilitiesApi, type Call, type SkillRef, type ToolName } from '../api/capabilities';

export default function ToolComposer({ token, skill, tools = ['notes.read', 'notes.write'], created }: {
  token: string; skill?: SkillRef; tools?: ToolName[]; created: (call: Call) => Promise<void>;
}) {
  const [tool, setTool] = useState<ToolName>(tools[0]);
  const [resource, setResource] = useState('project-notes');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return <form className="p4-form" onSubmit={event => {
    event.preventDefault(); setBusy(true); setError('');
    void capabilitiesApi.prepare(token, tool, tool === 'notes.write' ? { resource, text } : { resource }, skill)
      .then(created).catch(e => setError(e instanceof Error ? e.message : 'REQUEST_FAILED')).finally(() => setBusy(false));
  }}>
    {skill && <p>调用版本：{skill.skill_id} @ {skill.version}</p>}
    <label>工具<select aria-label="工具" value={tool} onChange={event => setTool(event.target.value as ToolName)}>{tools.map(name => <option key={name}>{name}</option>)}</select></label>
    <label>资源 ID<input aria-label="资源 ID" value={resource} pattern="[a-z][a-z0-9-]{0,47}" maxLength={48} required onChange={event => setResource(event.target.value)} /></label>
    {tool === 'notes.write' && <label>笔记内容<textarea aria-label="笔记内容" value={text} maxLength={4096} required onChange={event => setText(event.target.value)} /></label>}
    <p className="muted">资源须有服务端显式授权。写入先申请独立审批；读取也经过 Schema、额度及权限检查。</p>
    <button disabled={busy} type="submit">准备工具调用</button>{error && <p role="alert" className="error-text">{error}</p>}
  </form>;
}
