import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: '需求智能工作台', description: '从需求澄清到软件需求交付的协作工作台' };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="zh-CN"><body>{children}</body></html>; }
