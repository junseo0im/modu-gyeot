import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {title:'곁 · 함께 확인해요',description:'공식 기록을 확인하는 곁의 제한된 개발 버전'};

export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="ko"><body>{children}</body></html>;
}