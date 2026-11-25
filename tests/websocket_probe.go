// Local A/B acceptance client; the ephemeral test key is read from stdin.
package main
import("encoding/json";"fmt";"io";"net/http";"os";"strings";"time";"github.com/gorilla/websocket")
func main(){
 key,err:=io.ReadAll(os.Stdin);if err!=nil{panic(err)}
 c,_,err:=websocket.DefaultDialer.Dial(os.Args[1],http.Header{"Authorization":[]string{"Bearer "+string(key)}});if err!=nil{panic(err)};defer c.Close()
 _=c.SetReadDeadline(time.Now().Add(20*time.Second))
 err=c.WriteJSON(map[string]any{"type":"response.create","model":os.Args[2],"input":[]any{map[string]any{"role":"user","content":"hello"}}});if err!=nil{panic(err)}
 saw:=false
 for { _,raw,err:=c.ReadMessage();if err!=nil{panic(err)};var v map[string]any;if json.Unmarshal(raw,&v)!=nil{panic("invalid reply")};saw=saw||strings.Contains(string(raw),"native OK");if v["type"]=="error"{panic(string(raw))};if v["type"]=="response.completed"{if !saw{panic("missing reply")};fmt.Println("native websocket completed");return} }
}
