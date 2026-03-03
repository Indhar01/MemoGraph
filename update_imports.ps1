# PowerShell script to update all imports from mnemo to recallgraph

Write-Host "Updating Python imports from 'mnemo' to 'recallgraph'..." -ForegroundColor Green

# Function to update file content
function Update-Imports {
    param (
        [string]$Path,
        [string]$Pattern
    )
    
    Get-ChildItem -Path $Path -Recurse -Filter $Pattern -ErrorAction SilentlyContinue | ForEach-Object {
        $content = Get-Content $_.FullName -Raw
        $originalContent = $content
        
        # Replace imports
        $content = $content -replace 'from mnemo\.', 'from recallgraph.'
        $content = $content -replace 'from mnemo import', 'from recallgraph import'
        $content = $content -replace 'import mnemo', 'import recallgraph'
        $content = $content -replace '"mnemo', '"recallgraph'
        $content = $content -replace "'mnemo", "'recallgraph"
        
        # Only write if content changed
        if ($content -ne $originalContent) {
            Set-Content -Path $_.FullName -Value $content -NoNewline
            Write-Host "  Updated: $($_.FullName)" -ForegroundColor Yellow
        }
    }
}

# Update recallgraph package files
Write-Host "`nUpdating recallgraph/ directory..." -ForegroundColor Cyan
Update-Imports -Path "recallgraph" -Pattern "*.py"

# Update test files  
Write-Host "`nUpdating tests/ directory..." -ForegroundColor Cyan
Update-Imports -Path "tests" -Pattern "*.py"

# Update example files
Write-Host "`nUpdating examples/ directory..." -ForegroundColor Cyan
Update-Imports -Path "examples" -Pattern "*.py"

Write-Host "`n✓ All imports updated!" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor White
Write-Host "1. Run: pip install -e '.[dev,all]'" -ForegroundColor White
Write-Host "2. Run: pytest" -ForegroundColor White  
Write-Host "3. Run: ruff check ." -ForegroundColor White
Write-Host "4. Run: ruff format ." -ForegroundColor White