/**
 * @file _app.jsx
 * @description App-wide chrome. Loads global stylesheet, Plus Jakarta Sans
 * (used by /privacy /terms /dpa /subprocessors via tailwind `font-plus-jakarta`),
 * and the global staging banner.
 */
import '../styles/globals.css'
import Head from 'next/head'
import { StagingBanner } from '../components/StagingBanner.jsx'

function MyApp({ Component, pageProps }) {
  return (
    <>
      <Head>
        <title>Broby Vets | Local website preview</title>
        <link rel="icon" href="/favicon.ico" />
        <link rel="icon" type="image/png" href="/images/broby-logo.png" />
      </Head>
      <StagingBanner />
      <Component {...pageProps} />
    </>
  )
}

export default MyApp
