"""Framework syntax hints; imports, mounting and effective policies require review."""

WEB_RULES = {
    "python": [
        ("Flask / FastAPI", r"@\w+(?:\.\w+)*\.(?:route|get|post|put|delete|patch|websocket)\s*\("),
        ("Django", r"\b(?:path|re_path|url)\s*\("),
    ],
    "javascript": [
        (
            "Express / Koa / Fastify",
            r"\b(?:app|router|server|fastify|\w*Router)\s*\.\s*(?:get|post|put|patch|delete|use|route|all)\s*\(",
        )
    ],
    "typescript": [
        (
            "Express / Fastify",
            r"\b(?:app|router|server|fastify|\w*Router)\s*\.\s*(?:get|post|put|patch|delete|use|route|all)\s*\(",
        ),
        ("NestJS", r"@(?:Get|Post|Put|Patch|Delete|All|Controller)\s*\("),
    ],
    "java": [
        (
            "Spring MVC",
            r"@(?:\w+\.)*(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b",
        ),
        (
            "JAX-RS / Servlet",
            r"@(?:\w+\.)*(?:Path|GET|POST|PUT|DELETE|PATCH|WebServlet)\b|\bvoid\s+do(?:Get|Post|Put|Delete)\s*\(",
        ),
    ],
    "kotlin": [
        (
            "Spring MVC",
            r"@(?:\w+\.)*(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b",
        ),
        ("Ktor", r"\b(?:routing|route|get|post|put|patch|delete|webSocket)\s*(?:\([^\n]*\)\s*)?\{"),
    ],
    "go": [
        (
            "net/http / Gin / Echo / Fiber",
            r"\b\w+\s*\.\s*(?:HandleFunc|Handle|GET|POST|PUT|PATCH|DELETE|Any|Group|Get|Post|Put|Delete)\s*\(",
        )
    ],
    "csharp": [
        (
            "ASP.NET",
            r"\b\w+\s*\.\s*Map(?:Get|Post|Put|Patch|Delete|Methods|Group|Controllers)\s*\(|\[\s*(?:HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete|Route)\b",
        )
    ],
    "php": [
        (
            "Laravel",
            r"\bRoute\s*::\s*(?:get|post|put|patch|delete|any|match|resource|apiResource|group)\s*\(",
        ),
        ("Symfony", r"#\[\s*(?:\w+\\)*Route\b"),
    ],
    "ruby": [
        (
            "Rails / Sinatra",
            r"(?m)^[ \t]*(?:get|post|put|patch|delete|resources|resource|match|mount|root)\b",
        )
    ],
    "rust": [
        ("Axum / Actix", r"\.route\s*\(|#\[\s*(?:\w+::)*(?:get|post|put|patch|delete|route)\s*\(")
    ],
    "swift": [
        (
            "Vapor",
            r"\b(?:app|routes|router|grouped)\s*\.\s*(?:get|post|put|patch|delete|on|group)\s*\(",
        )
    ],
}
CLI_PATTERN = (
    r"\b__name__\s*==|\bArgumentParser\s*\(|@(?:\w+\.)*(?:command|option|Command)\b"
    r"|\b(?:program|commander|flag)\.(?:command|argument|option|Parse)\s*\("
    r"|\b(?:func|fn|fun|int)\s+main\s*\(|\bstatic\s+(?:void|int|Task(?:<int>)?)\s+(?:main|Main)\s*\("
    r"|\b(?:cobra\.Command|CommandLine)\b|#\[\s*(?:command|arg)\b"
)
BACKGROUND_PATTERN = (
    r"@(?:\w+\.)*(?:task|shared_task|job|periodic_task|KafkaListener|RabbitListener|JmsListener|Scheduled)\b"
    r"|\b(?:consume|subscribe|process_message|on_message|basic_consume|Consume|ExecuteAsync|perform)\s*\("
)
GUARDS = (
    r"\b(?:PreAuthorize|Secured|RolesAllowed|Authorize|AllowAnonymous|UseAuthorization|RequireAuthorization|"
    r"SecurityFilterChain|authorizeHttpRequests|SecurityWebFilterChain|UseAuthentication|"
    r"login_required|permission_required|permission_classes|authentication_classes|Depends|"
    r"before_action|skip_before_action|middleware|authenticate|UseGuards)\b"
)
RESOURCES = (
    r"\b(?:execute|executeQuery|createQuery|Raw|Exec|query|save|delete|remove|unlink|"
    r"readFile|writeFile|readFileSync|writeFileSync|open|sendFile|exec|system|spawn|"
    r"ProcessBuilder|fetch|HttpClient|RestTemplate|deserialize|unserialize)\s*\("
)
