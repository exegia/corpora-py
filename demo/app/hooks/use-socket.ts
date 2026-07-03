import { useAtom } from "jotai"
import { statusAtom } from "../atoms"
import { useEffect } from "react"
import { io } from "socket.io-client"

export const useWebSocket = () => {
  const [status, setStatus] = useAtom(statusAtom)
  const socket = io({ autoConnect: false })
  const connect = async () => {
    if (socket.connected) return
    socket.connect()
    setStatus(socket.connected ? "open" : "closed")
  }

  const disconnect = async () => {
    socket.disconnect()
    setStatus(socket.disconnected ? "closed" : "idle")
  }

  useEffect(() => {
    socket.once("connect", () => {
      setStatus("open")
    })
    socket.once("disconnect", () => {
      setStatus("closed")
    })
  }, [])

  return {
    connect,
    disconnect,
    status
  }
}
