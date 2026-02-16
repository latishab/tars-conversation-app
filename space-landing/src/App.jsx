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
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="border-b bg-white/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-purple-600 rounded-lg flex items-center justify-center">
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
                <Github className="w-4 h-4 mr-2" />
                GitHub
              </a>
            </Button>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="container mx-auto px-4 py-16 text-center">
        <div className="max-w-3xl mx-auto space-y-6">
          <div className="flex justify-center gap-2 flex-wrap">
            <Badge>AI Assistant</Badge>
            <Badge variant="secondary">v1.0.0</Badge>
            <Badge className="bg-green-600">TARS App</Badge>
          </div>
          
          <h2 className="text-5xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Real-time Conversational AI
          </h2>
          
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Voice-to-voice AI with transcription, vision, and intelligent conversation using 
            Speechmatics, ElevenLabs, DeepInfra LLM, and Moondream vision.
          </p>

          <div className="flex gap-4 justify-center flex-wrap">
            <Button size="lg" className="gap-2">
              <Download className="w-5 h-5" />
              Install on TARS Robot
            </Button>
            <Button size="lg" variant="outline" className="gap-2" asChild>
              <a href="https://github.com/latishab/tars-conversation-app" target="_blank" rel="noopener noreferrer">
                View Documentation
                <ExternalLink className="w-4 h-4" />
              </a>
            </Button>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="container mx-auto px-4 py-16">
        <h3 className="text-3xl font-bold text-center mb-12">Features</h3>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature, idx) => (
            <Card key={idx} className="border-2 hover:border-primary/50 transition-colors">
              <CardHeader>
                <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center text-primary mb-4">
                  {feature.icon}
                </div>
                <CardTitle className="text-lg">{feature.title}</CardTitle>
                <CardDescription>{feature.description}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      {/* Installation Section */}
      <section className="container mx-auto px-4 py-16">
        <Card className="max-w-3xl mx-auto border-2">
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
                  <div className="flex-shrink-0 w-8 h-8 bg-primary text-primary-foreground rounded-full flex items-center justify-center font-bold">
                    {idx + 1}
                  </div>
                  <div className="flex-1">
                    <p className="font-semibold">{item.step}</p>
                    <p className="text-sm text-muted-foreground">{item.detail}</p>
                  </div>
                </li>
              ))}
            </ol>

            <div className="bg-muted p-4 rounded-lg">
              <h4 className="font-semibold mb-2">Required API Keys:</h4>
              <ul className="text-sm space-y-1 text-muted-foreground">
                <li>• <code className="bg-background px-2 py-0.5 rounded">DEEPINFRA_API_KEY</code> - For LLM (DeepInfra)</li>
                <li>• <code className="bg-background px-2 py-0.5 rounded">SPEECHMATICS_API_KEY</code> or <code className="bg-background px-2 py-0.5 rounded">DEEPGRAM_API_KEY</code> - For STT</li>
                <li>• <code className="bg-background px-2 py-0.5 rounded">ELEVENLABS_API_KEY</code> (optional) - For premium TTS</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Tech Stack */}
      <section className="container mx-auto px-4 py-16">
        <h3 className="text-3xl font-bold text-center mb-8">Tech Stack</h3>
        <div className="flex flex-wrap justify-center gap-3 max-w-3xl mx-auto">
          {techStack.map((tech, idx) => (
            <Badge key={idx} variant="secondary" className="text-sm px-4 py-2">
              {tech}
            </Badge>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t bg-white/50 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-8 text-center space-y-4">
          <p className="text-muted-foreground">
            Built with TarsApp framework • TARS Project
          </p>
          <div className="flex justify-center gap-4 text-sm">
            <a 
              href="https://github.com/latishab/tars-conversation-app" 
              target="_blank" 
              rel="noopener noreferrer"
              className="text-primary hover:underline inline-flex items-center gap-1"
            >
              GitHub Repository
              <ExternalLink className="w-3 h-3" />
            </a>
            <span className="text-muted-foreground">•</span>
            <a 
              href="https://huggingface.co/spaces/latishab/tars-conversation-app" 
              target="_blank" 
              rel="noopener noreferrer"
              className="text-primary hover:underline inline-flex items-center gap-1"
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
