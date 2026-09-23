import { useState } from 'react'
import { useRouter } from 'next/router'
import {
  FileText,
  Check,
  Menu,
  X,
  Zap,
  Users,
  Brain
} from 'lucide-react'
import { VideoPlayer } from '../components/VideoPlayer.jsx'
import { FAQSection } from '../components/FAQSection.jsx'

// App URL for login redirect - configure via environment variable
const APP_URL = process.env.NEXT_PUBLIC_APP_URL || 'http://127.0.0.1:3100'

export default function Home() {
  const router = useRouter()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  // Features data
  const features = [
    {
      icon: <FileText className="w-6 h-6" />,
      title: "Consultation Summary",
      description: "Transform consultations into comprehensive, structured notes automatically"
    },
    {
      icon: <FileText className="w-6 h-6" />,
      title: "Summary Templates",
      description: "Customisable templates to match your practice workflow"
    },
    {
      icon: <Zap className="w-6 h-6" />,
      title: "Data Extraction",
      description: "Automatically extract key medical data and insights"
    },
    {
      icon: <Users className="w-6 h-6" />,
      title: "Multi-lingual and Dialect Support",
      description: "Our AI understands various languages such as Mandarin, Malay, Tamil and more"
    },
    {
      icon: <Brain className="w-6 h-6" />,
      title: "Adaptive Learning",
      description: "Tracks corrections you make to AI-generated consult summaries, spots where the model got things wrong, and applies those lessons so future summaries match your style and preferences."
    }
  ]

  return (
    <div className="min-h-screen bg-background">
      {/* Navigation */}
      <nav className="fixed top-0 w-full bg-background/95 backdrop-blur-sm border-b border-border z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            {/* Logo */}
            <div className="flex items-center">
              <div className="flex-shrink-0 flex items-center gap-2">
                <img src="/images/broby-logo.png" alt="Broby Vets Logo" className="w-10 h-10" />
                <div className="text-2xl font-bold" style={{color: '#17A2B8'}}>
                  Broby Vets
                </div>
              </div>
            </div>

            {/* Desktop Navigation */}
            <div className="hidden md:flex items-center space-x-4">
              <a
                href={`${APP_URL}/`}
                className="text-text-secondary hover:text-text-primary font-medium px-4 py-2 transition-colors"
              >
                Login
              </a>
              <button
                onClick={() => router.push('/contact')}
                className="bg-primary hover:bg-primary-dark text-white font-semibold px-6 py-2 rounded-lg transition-all duration-300 hover:shadow-[0_4px_12px_rgba(23,162,184,0.3)]"
              >
                Book a Demo
              </button>
            </div>

            {/* Mobile menu button */}
            <div className="md:hidden">
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="text-text-secondary hover:text-text-primary"
              >
                {mobileMenuOpen ? <X /> : <Menu />}
              </button>
            </div>
          </div>
        </div>

        {/* Mobile menu */}
        {mobileMenuOpen && (
          <div className="md:hidden bg-background border-b border-border">
            <div className="px-2 pt-2 pb-3 space-y-2">
              <a
                href={`${APP_URL}/`}
                className="block w-full text-left px-3 py-2 text-text-secondary hover:text-text-primary"
                onClick={() => setMobileMenuOpen(false)}
              >
                Login
              </a>
              <button
                onClick={() => {
                  setMobileMenuOpen(false)
                  router.push('/contact')
                }}
                className="block w-full bg-primary hover:bg-primary-dark text-white font-semibold px-3 py-2 rounded-lg transition-colors"
              >
                Book a Demo
              </button>
            </div>
          </div>
        )}
      </nav>

      {/* SECTION 1: Hero Section */}
      <section className="relative bg-white flex items-center min-h-screen md:h-screen pt-20 md:pt-16 pb-8 md:pb-0">
        <div className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8 w-full">
          <div className="text-left max-w-full">
            <h1 className="font-bold text-text-primary leading-tight text-2xl sm:text-3xl md:text-4xl lg:text-5xl mb-4 md:mb-6">
              Generic AI Scribes Mistake Breeds For Diseases.<br className="hidden sm:block" />
              <span className="sm:hidden"> </span>This One Was Built For Asia's Multilingual Veterinary Clinics.
            </h1>

            <p className="text-text-secondary text-base sm:text-lg md:text-xl leading-relaxed mb-6 md:mb-8 max-w-full md:max-w-[900px]">
              Built exclusively on veterinary consultations, so it understands breeds, species-specific conditions, and vet protocols that generic AI gets wrong.
            </p>

            <button
              onClick={() => router.push('/contact')}
              className="inline-block bg-primary hover:bg-primary-dark text-white font-semibold px-6 py-3 md:px-10 md:py-4 rounded-lg transition-all duration-300 hover:shadow-[0_4px_12px_rgba(23,162,184,0.3)] text-base md:text-lg"
            >
              Book a Demo
            </button>
          </div>
        </div>
      </section>

      {/* SECTION 2: Video Demo */}
      <section className="relative px-4 sm:px-6 lg:px-8 bg-white mt-0 md:-mt-[10vh] pb-12 md:pb-24">
        <div className="mx-auto max-w-full md:max-w-[min(1400px,90vw)]">
          {/* Video Player */}
          <div className="mb-8 md:mb-[60px]">
            <VideoPlayer src="/demo-video.mp4" />
          </div>

          {/* 2x2 Checkmark Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6">
            <div className="flex items-start gap-2 md:gap-3">
              <Check className="w-4 h-4 md:w-5 md:h-5 text-brand-teal flex-shrink-0 mt-1" />
              <p className="text-sm md:text-base text-text-secondary">Trained for Asian languages and dialects</p>
            </div>
            <div className="flex items-start gap-2 md:gap-3">
              <Check className="w-4 h-4 md:w-5 md:h-5 text-brand-teal flex-shrink-0 mt-1" />
              <p className="text-sm md:text-base text-text-secondary">No training needed - interface looks like Excel</p>
            </div>
            <div className="flex items-start gap-2 md:gap-3">
              <Check className="w-4 h-4 md:w-5 md:h-5 text-brand-teal flex-shrink-0 mt-1" />
              <p className="text-sm md:text-base text-text-secondary">Complete medical records in seconds</p>
            </div>
            <div className="flex items-start gap-2 md:gap-3">
              <Check className="w-4 h-4 md:w-5 md:h-5 text-brand-teal flex-shrink-0 mt-1" />
              <p className="text-sm md:text-base text-text-secondary">Easy copy paste into existing practice management</p>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 3: Problem Amplification */}
      <section className="py-12 md:py-20 lg:py-[120px] px-4 sm:px-6 lg:px-8 bg-background-secondary">
        <div className="max-w-[900px] mx-auto text-left">
          <p className="text-base md:text-lg lg:text-[22px] leading-relaxed text-text-secondary mb-4 md:mb-6 lg:mb-8">
            Documentation shouldn't take longer than the consultation itself.
          </p>

          <p className="text-base md:text-lg lg:text-[22px] leading-relaxed text-text-secondary mb-4 md:mb-6 lg:mb-8">
            Yet Asia's vets spend 2 hours daily recreating multilingual conversations from memory - losing critical details, staying late, sacrificing evenings for paperwork that should take seconds.
          </p>

          <p className="text-base md:text-lg lg:text-[22px] leading-relaxed text-text-secondary mb-4 md:mb-6 lg:mb-8">
            We built the first AI scribe trained on Asia's veterinary consultations. Multilingual. Species-specific. Zero learning curve.
          </p>

          <p className="text-base md:text-lg lg:text-[22px] leading-relaxed text-text-secondary mb-4 md:mb-6 lg:mb-8">
            Vets from Singapore to Japan are saving 40+ hours monthly.
          </p>

          <p className="text-xl md:text-2xl lg:text-[28px] font-bold text-brand-teal mb-6 md:mb-8 lg:mb-12">
            Welcome to Broby Vets.
          </p>

          <button
            onClick={() => router.push('/contact')}
            className="inline-block bg-primary hover:bg-primary-dark text-white font-semibold px-6 py-3 md:px-10 md:py-4 rounded-lg transition-all duration-300 hover:shadow-[0_4px_12px_rgba(23,162,184,0.3)] text-base md:text-lg"
          >
            Book a Demo
          </button>
        </div>
      </section>

      {/* SECTION 4: Features */}
      <section id="features" className="py-12 md:py-20 lg:py-[120px] px-4 sm:px-6 lg:px-8 bg-white">
        <div className="max-w-[1200px] mx-auto">
          {/* Feature 1: Templates - Text Left, Video Right */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 items-center mb-[100px]">
            <div className="text-left">
              <h3 className="text-[28px] font-bold text-text-primary mb-6">
                Your Format. Your Protocols. Instantly.
              </h3>
              <p className="text-lg text-text-secondary leading-relaxed"
                 style={{lineHeight: '1.7'}}>
                Generic AI forces you into their format. Broby Vets adapts to yours. Create unlimited templates matching your exact documentation style - by consultation type, species, or protocol. Choose before submitting. Get notes formatted your way, every time.
              </p>
            </div>
            <div>
              <VideoPlayer src="/feature-templates.mp4" />
            </div>
          </div>

          {/* Feature 2: Excel-like Dashboard - Video Left, Text Right */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
            <div className="md:order-1">
              <VideoPlayer src="/feature-dashboard.mp4" />
            </div>
            <div className="text-left md:order-2">
              <h3 className="text-[28px] font-bold text-text-primary mb-6">
                Familiar Interface, Zero Learning Curve
              </h3>
              <p className="text-lg text-text-secondary leading-relaxed"
                 style={{lineHeight: '1.7'}}>
                If you know Excel, you already know how to use this. Search past records, filter by date, export with one click. Most vets are comfortable within 30 minutes.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 5: Export to Practice Software */}
      <section className="py-12 md:py-20 lg:py-[120px] px-4 sm:px-6 lg:px-8 bg-background-secondary">
        <div className="max-w-[1200px] mx-auto text-center">
          <h2 className="text-[28px] md:text-[32px] font-bold text-text-primary mb-6">
            Export to your practice software in one click
          </h2>
          <p className="text-lg text-text-secondary leading-relaxed mb-12 max-w-[900px] mx-auto"
             style={{lineHeight: '1.7'}}>
            No more switching tabs or copy-pasting between systems. Your consultation notes transfer directly to your practice software - processed in under 10 seconds and ready to go. More integrations coming soon.
          </p>
          <div className="mx-auto max-w-full md:max-w-[min(1400px,90vw)]">
            <VideoPlayer src="/export-software.mp4" />
          </div>
        </div>
      </section>

      {/* SECTION 6: Mobile App */}
      <section className="py-12 md:py-20 lg:py-[120px] px-4 sm:px-6 lg:px-8 bg-white overflow-hidden">
        <div className="max-w-[1200px] mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
            <div className="text-left">
              <h3 className="text-[28px] font-bold text-text-primary mb-6">
                Mobile app for on-the-go recording
              </h3>
              <p className="text-lg text-text-secondary leading-relaxed"
                 style={{lineHeight: '1.7'}}>
                Record consultations on your phone, edit on your desktop - everything syncs automatically. Works with any workflow.
                Download on Google Play Store. iOS app coming soon.
              </p>
            </div>
            <div>
              <img
                src="/mobile-app.png"
                alt="Mobile app interface"
                className="w-full h-auto"
              />
            </div>
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <FAQSection />

      {/* Footer */}
      <footer className="bg-background-secondary border-t border-border py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="mb-4 md:mb-0">
              <div className="flex items-center gap-2 mb-2">
                <img src="/images/broby-logo.png" alt="Broby Vets Logo" className="w-8 h-8" />
                <div className="text-2xl font-bold" style={{color: '#17A2B8'}}>
                  Broby Vets
                </div>
              </div>
              <p className="text-text-secondary text-sm">
                © 2025 Broby Vets. All rights reserved.
              </p>
            </div>

            <div className="flex flex-wrap gap-x-6 gap-y-2 justify-center md:justify-end">
              <a
                href="/terms"
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                Terms
              </a>
              <a
                href="/privacy"
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                Privacy
              </a>
              <a
                href="/dpa"
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                DPA
              </a>
              <a
                href="/subprocessors"
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                Sub-processors
              </a>
              <a
                href="/contact"
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                Contact
              </a>
            </div>
          </div>
        </div>
      </footer>

    </div>
  )
}
