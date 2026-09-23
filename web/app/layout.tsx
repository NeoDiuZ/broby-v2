import './utilities.css';
import './tokens.css';
import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={title:'Broby | Clinic workspace',description:'Patient records, consultation capture and clinic operations.',icons:{icon:'/favicon.png'}};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
