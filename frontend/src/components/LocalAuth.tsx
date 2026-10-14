import { createContext, useContext, useState, Fragment, type ReactNode } from 'react';

const AuthContext = createContext({ token: '', setToken: (_value: string) => {} });
export function LocalAuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState({ token:'', generation:0 });
  const setToken = (token:string) => setAuth(previous => ({ token,generation:previous.generation+1 }));
  // Drop cached protected page state when credentials change; never use the token as a React key.
  return <AuthContext.Provider value={{ token:auth.token, setToken }}><Fragment key={auth.generation}>{children}</Fragment></AuthContext.Provider>;
}
export const useLocalAuth = () => useContext(AuthContext);
export function LocalAuthForm() {
  const { token, setToken } = useLocalAuth();
  const [value, setValue] = useState('');
  return <section className="panel"><div className="panel-heading"><h2>本地开发授权</h2>{token && <button onClick={() => setToken('')}>退出授权</button>}</div>
    <p>使用项目 .env 中的管理员 Token。仅保存在当前页面内存，刷新后清除；这不是模型 API Key。</p>
    {!token && <form className="auth-form" onSubmit={event => { event.preventDefault(); setToken(value.trim()); setValue(''); }}>
      <label>管理员 Token<input aria-label="管理员 Token" type="password" autoComplete="off" value={value} onChange={event => setValue(event.target.value)} required minLength={32}/></label>
      <button type="submit">授权当前页面</button>
    </form>}
    {token && <span className="badge">当前页面已设置授权凭据</span>}
  </section>;
}
