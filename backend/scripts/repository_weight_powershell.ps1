# Read JSON source text from stdin and parse it. Never dot-source or invoke it.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Get-WeightDecisionIncrement($Node) {
    switch ($Node.GetType().Name) {
        'IfStatementAst' { return $Node.Clauses.Count }
        'SwitchStatementAst' { return $Node.Clauses.Count }
        { $_ -in @('ForStatementAst', 'ForEachStatementAst', 'WhileStatementAst',
                   'DoWhileStatementAst', 'DoUntilStatementAst', 'CatchClauseAst',
                   'TernaryExpressionAst', 'PipelineChainAst') } { return 1 }
        'BinaryExpressionAst' {
            if ($Node.Operator.ToString() -in @('And', 'Or', 'QuestionQuestion')) { return 1 }
        }
    }
    return 0
}

function Get-WeightUnit($SourcePath, $Body, $Owner, $Name, $Extent, $ParameterCount) {
    $Complexity = 1
    foreach ($Node in $Body.FindAll({ param($Candidate) $true }, $true)) {
        $Parent = $Node.Parent
        while ($null -ne $Parent -and $Parent -isnot [System.Management.Automation.Language.FunctionDefinitionAst]) {
            $Parent = $Parent.Parent
        }
        if ([object]::ReferenceEquals($Parent, $Owner)) {
            $Complexity += Get-WeightDecisionIncrement $Node
        }
    }
    return @{
        path = $SourcePath; name = $Name
        line = $Extent.StartLineNumber; end_line = $Extent.EndLineNumber
        length = $Extent.EndLineNumber - $Extent.StartLineNumber + 1
        parameters = $ParameterCount; metric = 'powershell_ast_decisions'; complexity = $Complexity
    }
}

function Get-WeightScriptFunctions($Item) {
    $Tokens = $null
    $ParseErrors = $null
    $Tree = [System.Management.Automation.Language.Parser]::ParseInput($Item.source, [ref]$Tokens, [ref]$ParseErrors)
    if ($null -eq $Tree -or $ParseErrors.Count -ne 0) { throw 'Unmeasurable PowerShell syntax' }
    Get-WeightUnit $Item.path $Tree $null '<script>' $Tree.Extent 0
    $Functions = $Tree.FindAll({
        param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true)
    foreach ($Function in $Functions) {
        $ParameterCount = @($Function.Parameters).Count
        if ($null -ne $Function.Body.ParamBlock) { $ParameterCount = $Function.Body.ParamBlock.Parameters.Count }
        Get-WeightUnit $Item.path $Function.Body $Function $Function.Name $Function.Extent $ParameterCount
    }
}

$Items = ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
$Functions = @(foreach ($Item in $Items) { Get-WeightScriptFunctions $Item })
@{ version = $PSVersionTable.PSVersion.ToString(); functions = $Functions } | ConvertTo-Json -Depth 6 -Compress
