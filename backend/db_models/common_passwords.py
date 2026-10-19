"""
Passwords that are 8+ characters long (shorter ones are refused anyway) but still among the most common in leaked
password lists, so they're the first ones anyone guessing would try. Compared in lowercase.
"""

COMMON_PASSWORDS = frozenset("""
12345678 123456789 1234567890 12341234 12344321 11223344 11112222 12121212 12312312 123123123 123456123 123321123
87654321 98765432 987654321 9876543210 01234567 0123456789 11111111 00000000 22222222 88888888 99999999
123456789a 12345678a 1234567890a a12345678 a123456789 1q2w3e4r 1q2w3e4r5t 1q2w3e4r5t6y 1qaz2wsx 1qaz2wsx3edc
zaq12wsx zaq1zaq1 zaq1xsw2 q1w2e3r4 q1w2e3r4t5 q1w2e3r4t5y6 qwer1234 qwerty12 qwerty123 qwerty1234 qwertyui
qwertyuiop qwertyuiop123 asdfghjk asdfghjkl asdf1234 asdfasdf zxcvbnm1 zxcvbnm123 zxcvbnmm 1234qwer 1234asdf
1234abcd abcd1234 abcdefgh abcdefg1 abcdefgh1 abc12345 abc123456 abcabcabc aaaaaaaa1 aa123456 aa12345678
password password1 password12 password123 password1234 password! password1! password123! passw0rd p@ssword
p@ssw0rd pa55word pa55w0rd passwort motdepasse contraseña contrasena wachtwoord salasana
iloveyou iloveyou1 iloveyou2 iloveyou123 ilovegod loveyou1 lovelove lovelove1 sweetheart sweetie1 princess
princess1 sunshine sunshine1 starwars starwars1 whatever whatever1 football football1 baseball baseball1
basketball soccer123 hockey123 superman superman1 batman123 spiderman spiderman1 trustno1 letmein1 letmein123
welcome1 welcome123 welcome2 changeme changeme1 changeme123 newpassword default1 administrator admin123
admin1234 adminadmin root1234 rootroot test1234 test12345 testtest testing1 testing123 guest123 user1234
qazwsxedc qazwsx123 computer computer1 internet internet1 michael1 jennifer jordan23 jessica1 charlie1
corvette mustang1 ferrari1 mercedes yankees1 liverpool chelsea1 arsenal1 dragon12 dragon123 monkey12
monkey123 shadow12 master12 master123 mastermind blink182 pokemon1 pokemon123 minecraft minecraft1 fortnite
roblox123 pussycat butterfly butterfly1 chocolate chocolate1 cookie123 flower123 purple123 diamond1 midnight
midnight1 freedom1 hello123 hello1234 helloworld secret123 summer2023 summer2024 summer2025 summer2026
winter2024 winter2025 winter2026 spring2025 autumn2025 january1 december password2023 password2024
password2025 password2026 canada123 toronto1 montreal vancouver 1234qwerasdf 147258369 159753456 159357456
123654789 147852369 741852963 963852741 258456789 135792468 5201314520 woaini1314 aaaaaaaa abcd12345
qwerty11 qwerty01 qwerty00 q1234567 qq123456 asd12345 zxc12345 1q2w3e4r! 123qweasd 123qweasdzxc
qweasdzxc qweasd123 zxcasdqwe passpass loveme123 money123 iloveu123 michelle1 jessica123 nicole123
""".split())
