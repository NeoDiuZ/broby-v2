import { useState } from 'react'
import { Plus, Minus } from 'lucide-react'

export function FAQSection() {
  const [openIndex, setOpenIndex] = useState(null)

  const faqs = [
    {
      question: "How accurate is the transcription?",
      answer: (
        <>
          <p className="mb-4">
            Broby Vets is highly accurate and purpose-built for veterinary consultations. Our AI has been trained on hundreds of real veterinary conversations, so it understands and captures veterinary terminology—from medical abbreviations like "CBC" and "BCS" to specific drug names like "Cephalexin."
          </p>
          <p className="mb-4">
            But here's what makes us different: <strong>our system learns from you</strong>. Every time you edit a consultation summary, Broby takes note of the correction and adjusts for future transcriptions. This means the more you use Broby, the more accurate it becomes for your specific practice style and terminology. It's like having an assistant that gets better at understanding you every single day.
          </p>
          <p>
            All summaries are fully editable, so you always have complete control over the final notes before they're saved.
          </p>
        </>
      )
    },
    {
      question: "Does it integrate with my existing practice management system?",
      answer: (
        <>
          <p className="mb-4">
            Currently, Broby works alongside your existing practice management system rather than directly integrating with it. You can easily copy and paste the generated consultation notes into your PMS, or export them as a PDF for your records.
          </p>
          <p>
            We've designed the workflow to be simple and fast—most vets find it takes just seconds to transfer notes into their system. Direct integrations with popular veterinary software platforms are on our roadmap as we continue to grow.
          </p>
        </>
      )
    },
    {
      question: "What happens to the audio recordings? Is my data secure?",
      answer: (
        <>
          <p className="mb-4">
            <strong>Your data security is our top priority.</strong> Here's how we protect your information:
          </p>
          <p className="mb-3">
            <strong>Audio recordings:</strong> Audio files are automatically deleted after 30 days. We only retain them temporarily to ensure accurate processing and give you time to review consultations if needed.
          </p>
          <p className="mb-3">
            <strong>Transcripts:</strong> Consultation transcripts are retained indefinitely in your secure account, so you always have access to your records.
          </p>
          <p className="mb-3">
            <strong>Security measures:</strong> All data—both recordings and transcripts—are encrypted in transit and at rest. Only Broby's secure processing systems can access recordings during the transcription process. Your team can only access the transcripts and summaries, never the raw audio files.
          </p>
          <p>
            <strong>Access control:</strong> Only authorized users from your clinic can access your consultation transcripts. We never share your data with third parties, and you maintain full ownership of all your veterinary records.
          </p>
        </>
      )
    },
    {
      question: "How long does it take to generate the notes?",
      answer: (
        <>
          <p className="mb-4">
            <strong>Lightning fast.</strong> Once you click submit at the end of a consultation, Broby generates your summary in approximately 5 seconds, depending on the recording length and your internet speed.
          </p>
          <p>
            Whether your consultation was 5 minutes or 30 minutes, the processing time remains consistent—so you can move seamlessly to your next patient without waiting around for notes to be ready.
          </p>
        </>
      )
    },
    {
      question: "What if the transcription is wrong? Can I edit it?",
      answer: (
        <>
          <p className="mb-4">
            <strong>Absolutely.</strong> You have full editing control over every consultation summary. You can:
          </p>
          <ul className="list-disc pl-6 mb-4 space-y-2">
            <li>Edit any section of the transcription directly in the app</li>
            <li>Add or delete information as needed</li>
            <li>Adjust medical terminology or formatting</li>
            <li>Make any changes before saving to your records</li>
          </ul>
          <p>
            And here's the best part: <strong>Broby learns from every edit you make.</strong> When you correct something, the system remembers that correction and applies it to future consultations. So the AI becomes increasingly personalized to your practice, your terminology, and your documentation style over time.
          </p>
        </>
      )
    },
    {
      question: "Do I need special equipment?",
      answer: (
        <>
          <p className="mb-4">
            <strong>No special equipment needed.</strong> Broby is a cloud-based tool that works on the devices you already use:
          </p>
          <p className="mb-3">
            <strong>On desktop/laptop:</strong> Simply open Broby in any web browser (Chrome, Safari, Firefox, Edge—they all work). If your computer has a built-in microphone, you're all set. No software downloads or installations required.
          </p>
          <p className="mb-3">
            <strong>On mobile:</strong> Download our free app available for both iOS (Apple) and Android devices. Perfect for recording consultations on the go.
          </p>
          <p className="mb-3">
            <strong>Seamless sync:</strong> Everything syncs automatically between your phone and computer. Start a recording on your phone, and it instantly appears on your desktop. Make an edit on your computer, and it updates on your mobile app. Your consultation notes are accessible wherever you need them.
          </p>
          <p>
            <strong>Internet connection:</strong> You'll need a stable internet connection to use Broby, but no special bandwidth requirements—standard clinic WiFi works perfectly fine.
          </p>
        </>
      )
    }
  ]

  const toggleFAQ = (index) => {
    setOpenIndex(openIndex === index ? null : index)
  }

  return (
    <section id="faq" className="py-[120px] px-4 sm:px-6 lg:px-8 bg-white">
      <div className="max-w-[900px] mx-auto">
        {/* Header */}
        <h2 className="text-[42px] font-bold text-text-primary text-center mb-4">
          Frequently Asked Questions
        </h2>

        {/* FAQ Accordion */}
        <div className="mt-12 space-y-4">
          {faqs.map((faq, index) => (
            <div
              key={index}
              className="border border-border rounded-lg overflow-hidden transition-all duration-200 hover:border-primary/50"
            >
              <button
                onClick={() => toggleFAQ(index)}
                className="w-full flex items-center justify-between p-6 text-left bg-white hover:bg-background-secondary/50 transition-colors duration-200"
              >
                <h3 className="text-xl font-semibold text-text-primary pr-8">
                  {faq.question}
                </h3>
                <div className="flex-shrink-0 transition-transform duration-300" style={{
                  transform: openIndex === index ? 'rotate(180deg)' : 'rotate(0deg)'
                }}>
                  {openIndex === index ? (
                    <Minus className="w-6 h-6 text-primary" />
                  ) : (
                    <Plus className="w-6 h-6 text-primary" />
                  )}
                </div>
              </button>

              <div
                className="transition-all duration-300 ease-in-out overflow-hidden"
                style={{
                  maxHeight: openIndex === index ? '1000px' : '0',
                  opacity: openIndex === index ? 1 : 0
                }}
              >
                <div className="p-6 pt-0 text-text-secondary leading-relaxed text-base">
                  {faq.answer}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Contact CTA */}
        <div className="mt-16 text-center">
          <h3 className="text-2xl font-bold text-text-primary mb-4">
            Still have questions?
          </h3>
          <p className="text-lg text-text-secondary mb-6">
            We're here to help! Contact our team to discuss how Broby can work for your practice.
          </p>
          <a
            href="/contact"
            className="inline-block bg-primary hover:bg-primary-dark text-white font-semibold px-8 py-3 rounded-lg transition-all duration-300 hover:shadow-[0_4px_12px_rgba(23,162,184,0.3)]"
          >
            Contact Us
          </a>
        </div>
      </div>
    </section>
  )
}
