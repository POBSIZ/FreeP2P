# FreeP2P 0.4.0 — 호스트 코드 103자, 참가 코드 60자

친구에게 보내는 코드를 더 짧게 만들었습니다. 호스트 연결 코드는 `f3h:`로 시작하는 103자, 참가 코드는 `f3g:`로 시작하는 60자입니다.
표시 이름을 코드에서 빼서 이름의 길이에 따라 코드가 늘어나지 않습니다. 친구 이름은 코드를 등록한 뒤 상대 프로그램의 응답을 받아 표시합니다.
응답을 받기 전에는 임시 이름이 보일 수 있습니다.

코드를 주고받는 순서는 같습니다. 월드를 여는 사람은 **코드 복사**를 눌러 친구에게 보내고, 친구가 돌려준 참가 코드를 등록하세요.
**함께할 사람 모두 0.4.0 이상으로 업데이트해야 합니다.** 새 버전은 `fpm1:`·`fpm2:` 코드도 읽을 수 있지만, 이전 앱은 새 코드를 읽지 못합니다.
업데이트한 뒤 새 코드를 서로 주고받으세요.

접속 인증 토큰과 인증서 지문의 길이는 각각 32바이트로 유지했습니다. 추가 서버는 필요하지 않습니다.
코드는 함께할 친구에게만 보내고 공개 게시판이나 방송 화면에 노출하지 마세요.

![호스트 연결 코드를 복사하는 화면](https://raw.githubusercontent.com/POBSIZ/FreeP2P/v0.4.0/docs/images/share-code.png)

화면의 코드는 설명용 예시이며 실제 연결에 사용할 수 없습니다.

## 다운로드

- **Windows PC:** `FreeP2P-0.4.0-windows-x64.zip`을 받아 모두 압축을 푸세요.
  `FreeP2P` 폴더 안의 `FreeP2P.exe`를 실행합니다. 옆의 `_internal` 폴더도 함께 있어야 합니다.
- **Mac M 시리즈:** `FreeP2P-0.4.0-darwin-arm64.zip`을 받아 압축을 풀고 `FreeP2P` 앱을 여세요.

Python은 따로 설치하지 않아도 됩니다. 프로그램을 실행하려면 위의 ZIP 파일을 받으세요.
`Source code`는 개발자용 소스이며 `.sha256`은 다운로드한 파일을 확인할 때 씁니다.
기존 앱에서 **앱 종료**를 누른 뒤 새 압축 파일을 다른 폴더에 풀어 실행하세요.

[화면을 보며 따라 하기](https://github.com/POBSIZ/FreeP2P/blob/main/docs/USER_GUIDE.md)
· [실행 경고가 뜰 때](https://github.com/POBSIZ/FreeP2P/blob/main/docs/SECURITY_WARNINGS.md)
· [연결이 안 될 때](https://github.com/POBSIZ/FreeP2P/blob/main/docs/TROUBLESHOOTING.md)

아직 시험 배포 중입니다. 실제 Minecraft 월드 입장과 장시간 플레이는 검증하지 않았습니다.
인터넷 환경에 따라 연결되지 않을 수 있습니다.
