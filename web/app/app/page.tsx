'use client';
import AuthGate from '@/components/AuthGate';
import {Workspace} from '@/lib/workspace';
import App from '@/components/App';
export default function Page(){return <AuthGate><Workspace><App/></Workspace></AuthGate>}
