import { Bot, Mic, Brain, Eye, Activity, Github, ExternalLink, Download } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { Button } from './components/ui/button'
import { Badge } from './components/ui/badge'

function App() {
  const features = [
    {
      icon: <Mic className="w-6 h-6" />,
      title: "Real-time Voice",
      description: "WebRTC audio streaming with Speechmatics or Deepgram transcription for natural conversations"
    },
    {
      icon: <Brain className="w-6 h-6" />,
      title: "Smart Memory",
      description: "Hybrid vector + BM25 search with ChromaDB for contextual conversation recall"
    },
    {
      icon: <Eye className="w-6 h-6" />,
      title: "Vision Analysis",
      description: "Real-time image understanding with Moondream for visual context awareness"
    },
    {
      icon: <Activity className="w-6 h-6" />,
      title: "Live Dashboard",
      description: "Gradio interface with TTFB metrics, latency charts, and conversation transcription"
    },
    {
      icon: <Bot className="w-6 h-6" />,
      title: "Emotional AI",
      description: "Realtime emotion monitoring detecting confusion, hesitation, and frustration patterns"
    },
    {
      icon: <Bot className="w-6 h-6" />,
      title: "Robot Control",
      description: "gRPC commands for gestures, eye expressions, and physical movements"
    }
  ]

  const techStack = [
    "Pipecat", "WebRTC", "Gradio", "ChromaDB", "gRPC", 
    "Speechmatics", "Deepgram", "ElevenLabs", "DeepInfra", "Moondream"
  ]

  return (
    <div className="min-h-screen bg-white">
      {/* Header */}
      <header className="border-b bg-white sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-black rounded-lg flex items-center justify-center">
              <Bot className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold">TARS Conversation App</h1>
              <p className="text-xs text-muted-foreground">Real-time AI Voice Assistant</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href="https://github.com/latishab/tars-conversation-app" target="_blank" rel="noopener noreferrer">
                <Github className="w-4 h-4" />
                GitHub
              </a>
            </Button>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="container mx-auto px-4 py-16">
        <div className="max-w-5xl mx-auto">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            {/* Left: Text */}
            <div className="space-y-6">
              <div className="flex gap-2 flex-wrap">
                <Badge>AI Assistant</Badge>
                <Badge variant="secondary">v1.0.0</Badge>
                <Badge variant="outline">TARS App</Badge>
              </div>

              <h2 className="text-5xl font-bold text-black">
                Real-time Conversational AI
              </h2>

              <p className="text-lg text-muted-foreground">
                Voice-to-voice AI with transcription, vision, and intelligent conversation using
                Speechmatics, ElevenLabs, DeepInfra LLM, and Moondream vision.
              </p>

              <div className="flex gap-4 flex-wrap">
                <Button size="lg">
                  <Download className="w-5 h-5" />
                  Install on TARS Robot
                </Button>
                <Button size="lg" variant="outline" asChild>
                  <a href="https://github.com/latishab/tars-conversation-app" target="_blank" rel="noopener noreferrer">
                    View Documentation
                    <ExternalLink className="w-4 h-4" />
                  </a>
                </Button>
              </div>
            </div>

            {/* Right: Image */}
            <div className="flex justify-center">
              <img
                src="/tars-sleepy.jpg"
                alt="TARS Robot"
                className="rounded-lg border shadow-lg w-full max-w-md"
              />
            </div>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="container mx-auto px-4 py-16 bg-gray-50">
        <h3 className="text-3xl font-bold text-center mb-12">Features</h3>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature, idx) => (
            <Card key={idx} className="hover:shadow-lg transition-shadow">
              <CardHeader>
                <div className="w-12 h-12 bg-black rounded-lg flex items-center justify-center text-white mb-4">
                  {feature.icon}
                </div>
                <CardTitle className="text-lg">{feature.title}</CardTitle>
                <CardDescription>{feature.description}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      {/* Installation and Tech Stack */}
      <section className="container mx-auto px-4 py-16">
        <div className="grid lg:grid-cols-2 gap-8 max-w-6xl mx-auto">
          {/* Installation */}
          <Card>
            <CardHeader>
              <CardTitle className="text-2xl">Installation on TARS Robot</CardTitle>
              <CardDescription>Install directly from the TARS dashboard in just a few steps</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <ol className="space-y-4">
                {[
                  { step: "Open TARS dashboard", detail: "Navigate to http://your-pi:8000" },
                  { step: "Go to App Store tab", detail: "Find the app management section" },
                  { step: "Enter Space ID", detail: "Type: latishab/tars-conversation-app" },
                  { step: "Click Install from HuggingFace", detail: "Wait for automatic installation" },
                  { step: "Configure API keys", detail: "Set up your API keys in .env.local" },
                  { step: "Click Start", detail: "Launch the conversation app" },
                  { step: "Access dashboard", detail: "Open http://your-pi:7860 for metrics" },
                ].map((item, idx) => (
                  <li key={idx} className="flex gap-4">
                    <div className="flex-shrink-0 w-8 h-8 bg-black text-white rounded-full flex items-center justify-center font-bold text-sm">
                      {idx + 1}
                    </div>
                    <div className="flex-1">
                      <p className="font-semibold text-sm">{item.step}</p>
                      <p className="text-xs text-muted-foreground">{item.detail}</p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="bg-gray-50 p-4 rounded-lg border">
                <h4 className="font-semibold mb-2 text-sm">Required API Keys:</h4>
                <ul className="text-xs space-y-1 text-muted-foreground">
                  <li>• <code className="bg-white px-2 py-0.5 rounded border">DEEPINFRA_API_KEY</code> - For LLM</li>
                  <li>• <code className="bg-white px-2 py-0.5 rounded border">SPEECHMATICS_API_KEY</code> or <code className="bg-white px-2 py-0.5 rounded border">DEEPGRAM_API_KEY</code> - For STT</li>
                  <li>• <code className="bg-white px-2 py-0.5 rounded border">ELEVENLABS_API_KEY</code> (optional) - For TTS</li>
                </ul>
              </div>
            </CardContent>
          </Card>

          {/* Tech Stack */}
          <Card>
            <CardHeader>
              <CardTitle className="text-2xl">Tech Stack</CardTitle>
              <CardDescription>Built with modern AI and robotics tools</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {techStack.map((tech, idx) => (
                  <Badge key={idx} variant="secondary" className="text-sm px-3 py-1">
                    {tech}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t bg-white">
        <div className="container mx-auto px-4 py-8 text-center space-y-4">
          <p className="text-muted-foreground">
            Built with TarsApp framework • TARS Project
          </p>
          <div className="flex justify-center gap-4 text-sm">
            <a
              href="https://github.com/latishab/tars-conversation-app"
              target="_blank"
              rel="noopener noreferrer"
              className="text-black hover:underline inline-flex items-center gap-1"
            >
              GitHub Repository
              <ExternalLink className="w-3 h-3" />
            </a>
            <span className="text-muted-foreground">•</span>
            <a
              href="https://huggingface.co/spaces/latishab/tars-conversation-app"
              target="_blank"
              rel="noopener noreferrer"
              className="text-black hover:underline inline-flex items-center gap-1"
            >
              HuggingFace Space
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
