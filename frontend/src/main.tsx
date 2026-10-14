import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles.css';
import './workflow.css';
import { LocalAuthProvider } from './components/LocalAuth';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><LocalAuthProvider><BrowserRouter><App /></BrowserRouter></LocalAuthProvider></React.StrictMode>,
);
